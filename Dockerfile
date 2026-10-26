FROM public.ecr.aws/lambda/python:3.13

ENV MODEL_DIR=/opt/models
ENV HF_HUB_OFFLINE=1

COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

COPY download_model.py ${LAMBDA_TASK_ROOT}/
RUN mkdir -p /opt/models && HF_HUB_OFFLINE=0 python ${LAMBDA_TASK_ROOT}/download_model.py

COPY utils.py lambda_function.py product_search.py designer_search.py home_search.py ${LAMBDA_TASK_ROOT}/

CMD ["lambda_function.lambda_handler"]
