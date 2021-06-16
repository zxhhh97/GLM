MODEL_TYPE="generation-base"
MODEL_ARGS="--block-lm \
            --cloze-eval \
            --num-layers 12 \
            --hidden-size 768 \
            --num-attention-heads 12 \
            --max-position-embeddings 512 \
            --tokenizer-model-type bert-base-uncased \
            --tokenizer-type BertWordPieceTokenizer \
            --load-pretrained ${CHECKPOINT_PATH}/blocklm-base-generation"