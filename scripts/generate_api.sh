#!/bin/bash
#CHECKPOINT_PATH=/root/data/checkpoints

script_path=$(realpath $0)
script_dir=$(dirname $script_path)
model_dir=$(dirname $script_dir)
CONFIG="$model_dir/config_tasks/model_blocklm_1.5_generation.sh"
#source $1
source $CONFIG

MPSIZE=1
MAXSEQLEN=512
MASTER_PORT=$(shuf -n 1 -i 10000-65535)

#SAMPLING ARGS
TEMP=0.9
#If TOPK/TOPP are 0 it defaults to greedy sampling, top-k will also override top-p
TOPK=20
TOPP=0

config_json="$script_dir/ds_config.json"

MASTER_PORT=${MASTER_PORT} python generate_db_api.py \
       --DDP-impl none \
       --generate \
       --no-load-rng \
       --no_print \
       --model-parallel-size $MPSIZE \
       --deepspeed_config ${config_json} \
       $MODEL_ARGS \
       --tokenizer-type BertWordPieceTokenizer \
       --tokenizer-model-type bert-large-uncased \
       #--fp16 \
       --cache-dir cache \
       --num-beams 1 \
       --length-penalty 0.0 \
       --out-seq-length $MAXSEQLEN \
       --seq-length 80 \
       --temperature $TEMP \
       --top_k $TOPK \
       --top_p $TOPP
