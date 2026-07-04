import logging

logger = logging.getLogger(__name__)

def test_exeception(raise_exception):
    if raise_exception:
        raise TypeError("message here")
    else:
        return "Passed"
    

try:
    value = test_exeception(raise_exception=True)
except Exception as e:
    logger.exception(e)
    value = "default"
finally:
    print(value)