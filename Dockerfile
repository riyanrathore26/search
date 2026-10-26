
FROM public.ecr.aws/lambda/python:3.13

ENV MODEL_DIR=/opt/models
ENV HF_HUB_OFFLINE=1

# Install Python libraries
COPY requirements.txt ${LAMBDA_TASK_ROOT}/

RUN pip install --no-cache-dir \
    -r ${LAMBDA_TASK_ROOT}/requirements.txt

# Download ONNX model
COPY download_model.py ${LAMBDA_TASK_ROOT}/

RUN mkdir -p /opt/models && \
    HF_HUB_OFFLINE=0 python \
    ${LAMBDA_TASK_ROOT}/download_model.py

# Copy Lambda function
COPY lambda_function.py ${LAMBDA_TASK_ROOT}/
COPY product_search.py ${LAMBDA_TASK_ROOT}/
COPY designer_search.py ${LAMBDA_TASK_ROOT}/
COPY home_search.py ${LAMBDA_TASK_ROOT}/


CMD ["lambda_function.lambda_handler"]
