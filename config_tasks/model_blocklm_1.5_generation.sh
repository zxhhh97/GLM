MODEL_TYPE="blocklm-1.5-generation"
MODEL_ARGS="--block-lm \
            --cloze-eval \
            --num-layers 30 \
            --hidden-size 1152 \
            --num-attention-heads 18 \
            --max-position-embeddings 512 \
            --tokenizer-model-type bert-large-uncased \
            --tokenizer-type BertWordPieceTokenizer \
<<<<<<< HEAD
            --load-pretrained ${model_dir}/blocklm-1.5-generation/200000/"
            #--load-pretrained ${CHECKPOINT_PATH}/blocklm-1.5-generation/200000/
=======
            --load-pretrained ${CHECKPOINT_PATH}/blocklm-1.5-generation"
>>>>>>> d43359ee572b4d3870c4bf0b1d270e616636ad8a
