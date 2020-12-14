# coding=utf-8
# Copyright (c) 2020, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Finetune utilities."""

import torch
from configure_data import prepare_tokenizer

from utils import print_rank_0
from utils import Timers
import mpu
from pretrain_gpt2 import setup_model_and_optimizer
from utils import load_checkpoint, save_checkpoint
from megatron.training import evaluate_and_print_results
from megatron.training import train_step
from megatron.training import training_log
from megatron.utils import check_adlr_autoresume_termination
from megatron.utils import reduce_losses


def process_batch(batch, args):
    """Process batch and produce inputs for the model."""
    tokens = batch['text'].long().cuda().contiguous()
    types = batch['types'].long().cuda().contiguous()
    labels = batch['label'].long().cuda().contiguous()
    attention_mask = batch['padding_mask'].float().cuda().contiguous()
    if args.fp16:
        attention_mask = attention_mask.half()

    return tokens, types, labels, attention_mask


def _cross_entropy_forward_step(batch, model, args, timers):
    """Simple forward step with cross-entropy loss."""
    # Get the batch.
    timers('batch generator').start()
    try:
        batch_ = next(batch)
    except BaseException:
        batch_ = batch
    tokens, types, labels, attention_mask = process_batch(batch_, args)
    timers('batch generator').stop()

    # Forward model.
    logits = model(tokens, attention_mask, types)

    # Cross-entropy loss.
    loss_func = torch.nn.CrossEntropyLoss()
    loss = loss_func(logits.contiguous().float(), labels)

    # Reduce loss for logging.
    reduced_loss = reduce_losses([loss])

    return loss, {'lm loss': reduced_loss[0]}


def build_data_loader(dataset, batch_size, num_workers, drop_last):
    """Data loader. Note that batch-size is the local (per GPU) batch-size."""

    # Sampler.
    world_size = mpu.get_data_parallel_world_size()
    rank = mpu.get_data_parallel_rank()
    sampler = torch.utils.data.distributed.DistributedSampler(
        dataset, num_replicas=world_size, rank=rank)

    # Data loader. Note that batch size is the per GPU batch size.
    data_loader = torch.utils.data.DataLoader(dataset,
                                              batch_size=batch_size,
                                              sampler=sampler,
                                              shuffle=False,
                                              num_workers=num_workers,
                                              drop_last=drop_last,
                                              pin_memory=True)

    return data_loader


def _build_infinite_size_dataloader(dataloader):
    """Build a looped dataloader with infinite size."""

    iterator = dataloader.__iter__()
    while True:
        try:
            yield iterator.__next__()
        except StopIteration:
            iterator = dataloader.__iter__()


def _build_train_valid_dataloaders(train_dataset, valid_dataset, args):
    """Traing and validation dataloaders."""
    print_rank_0('building train and validation dataloaders ...')
    # Training dataset.
    train_dataloader = build_data_loader(train_dataset, args.batch_size, args.num_workers, False)
    # Set the training iterations.
    args.train_iters_per_epoch = len(train_dataloader)
    args.train_iters = args.epochs * args.train_iters_per_epoch
    # Validation dataset. For this dataset, we do not need to set up
    # shuffling so we can just use a simple infinite loop.
    valid_dataloader_ = build_data_loader(valid_dataset, args.batch_size,
                                          args.num_workers, not args.keep_last)
    valid_dataloader = _build_infinite_size_dataloader(valid_dataloader_)

    return train_dataloader, valid_dataloader


def _train(model, optimizer, lr_scheduler, forward_step,
           train_dataloader, valid_dataloader, end_of_epoch_callback, args, timers):
    """Train the model."""

    # Turn on training mode which enables dropout.
    model.train()

    # Tracking loss.
    losses_dict_sum = {}

    # Starting epoch and iteration
    start_epoch = args.iteration // args.train_iters_per_epoch
    start_iteration = args.iteration % args.train_iters_per_epoch
    iteration = args.iteration

    # Memory reporting flag.
    report_memory_flag = True

    # For each remaining epoch
    timers('interval time').start()
    for epoch in range(start_epoch, args.epochs):
        print_rank_0('working on epoch {} ...'.format(epoch + 1))

        # Set the data loader epoch to shuffle the index iterator.
        train_dataloader.sampler.set_epoch(args.seed + epoch)

        # For all the batches in the dataset.
        for iteration_, batch in enumerate(train_dataloader):

            # Ignore the iterations before starting value
            if iteration_ < start_iteration:
                continue
            # Set to zero so the next epoch does not skip any batches.
            start_iteration = 0

            # Train for one step.
            losses_dict, skipped_iter = train_step(forward_step, batch, model,
                                                   optimizer, lr_scheduler)
            iteration += 1

            # Logging.
            report_memory_flag = training_log(losses_dict, losses_dict_sum,
                                              optimizer.param_groups[0]['lr'],
                                              iteration, optimizer.loss_scale,
                                              report_memory_flag, skipped_iter)

            # Autoresume
            if args.adlr_autoresume and \
                    (iteration % args.adlr_autoresume_interval == 0):
                check_adlr_autoresume_termination(iteration, model,
                                                  optimizer, lr_scheduler)

            # Checkpointing
            if args.save and args.save_interval and \
                    iteration % args.save_interval == 0:
                save_checkpoint(iteration, model, optimizer, lr_scheduler)

            # Evaluation
            if args.eval_interval and iteration % args.eval_interval == 0:
                prefix = 'iteration {}'.format(iteration)
                evaluate_and_print_results(prefix, forward_step,
                                           valid_dataloader, model,
                                           iteration, False)

        # Checkpointing at the end of each epoch.
        if args.save:
            save_checkpoint(iteration, model, optimizer, lr_scheduler, args)

        # Callback at the end of each epoch.
        if end_of_epoch_callback is not None:
            end_of_epoch_callback(model, epoch)


def finetune(args, train_valid_datasets_provider, model_type,
             forward_step=_cross_entropy_forward_step,
             end_of_epoch_callback_provider=None):
    """Main finetune function used across all tasks."""
    timers = Timers()
    tokenizer = prepare_tokenizer(args)
    # Train and validation data loaders.
    timers('train/valid/test dataset/dataloder').start()
    train_dataloader, valid_dataloader = None, None
    if args.epochs > 0:
        train_dataset, valid_dataset = train_valid_datasets_provider(args, tokenizer)
        train_dataloader, valid_dataloader = _build_train_valid_dataloaders(
            train_dataset, valid_dataset, args)
    timers('train/valid/test dataset/dataloder').stop()

    # Build calback function.
    timers('callback function').start()
    end_of_epoch_callback = None
    if end_of_epoch_callback_provider is not None:
        end_of_epoch_callback = end_of_epoch_callback_provider()
    timers('callback function').stop()

    # Build model, optimizer and learning rate scheduler.
    timers('model and optimizer').start()
    model, optimizer, lr_scheduler = setup_model_and_optimizer(args, model_type)
    timers('model and optimizer').stop()

    # If pretrained checkpoint is provided and we have not trained for
    # any iteration (i.e., iteration is zero), then load the pretrained
    # checkpoint.
    timers('pretrained checkpoint').start()
    if args.load is not None:
        load_checkpoint(model, optimizer, lr_scheduler, args)
        # This is critical when only model is loaded. We should make sure
        # master parameters are also updated.
        if args.fp16:
            optimizer._model_params_to_master_params()
    timers('pretrained checkpoint').stop()

    # Print setup timing.
    print_rank_0('done with setups ...')
    timers.log(['train/valid/test dataset/dataloder', 'callback function',
                'model and optimizer', 'pretrained checkpoint'])
    print_rank_0('training ...')

    # Finetune the model.
    if args.epochs > 0:
        _train(model, optimizer, lr_scheduler, forward_step,
               train_dataloader, valid_dataloader, end_of_epoch_callback, args, timers)
    # Or just evaluate.
    else:
        if end_of_epoch_callback is not None:
            print_rank_0('evaluation only mode, setting epoch to -1')
            end_of_epoch_callback(model, epoch=-1, output_predictions=True)

    print_rank_0('done :-)')
