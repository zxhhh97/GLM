import os
import csv
import time
import json
import torch
import pynvml
import argparse
from datetime import datetime

from arguments import get_args
from pretrain_glm import initialize_distributed
from pretrain_glm import set_random_seed
from pretrain_glm import get_masks_and_position_ids
from generate_tw import prepare_tokenizer, setup_model, generate_samples
from atomback import InteractDB


def main():
    """Main updating program."""
    print('Generate Samples')

    # Disable CuDNN.
    torch.backends.cudnn.enabled = False

    # Arguments.
    args = get_args()
    args.mem_length = args.seq_length + args.mem_length - 1

    # Pytorch distributed.
    initialize_distributed(args)

    # Random seeds for reproducability.
    set_random_seed(args.seed)

    #device = int(args.device)
    #torch.cuda.set_device(device)

    # get the tokenizer
    tokenizer = prepare_tokenizer(args)

    model = setup_model(args)

    # setting default batch size to 1
    args.batch_size = 1

    time_interval = int(args.time_interval)
    
    pynvml.nvmlInit()
    iodb = InteractDB(args.DBname)
    

    while True:
        print('checking')
        # handle = pynvml.nvmlDeviceGetHandleByIndex(device)
        # meminfo = pynvml.nvmlDeviceGetMemoryInfo(handle)
        # if meminfo.free <= 5*1024**3:
        #     continue
        #     print('device', device, 'using. skip.')
        outname = datetime.now().strftime('%m-%d_%H')
        datalist = iodb.query_docs(num = args.num_gen_at_once)
        datalist = list(datalist)
        contents = [iodb.process_doc(doc) for doc in datalist]
        #status = open(path,'w')
        for content, doc in zip(contents,datalist):
            generated,output_path = generate_samples(model, tokenizer, args, torch.cuda.current_device(), data = content, outname=outname)
            generated = iodb.postprocess_generated_content(generated)
            
            if not generated:
                generated = "Not suitable."
            else:
                new_doc = iodb.parse_doc(doc,generated)
                res =iodb.update_doc(new_doc)

            with open(output_path, "a") as output:
                output.write("Postprocessed: "+ generated + "\n")
            
            #status.write('fail ' + str(int(round(time.time() * 1000))))
            #status.close()

        #time.sleep(time_interval)
        #exit()

if __name__ == "__main__":
    main()
