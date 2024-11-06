"""
MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import logging
import sys

#####################################################################
def CommonLogger(DEBUG=False):
    logger = logging.getLogger('__COMMONLOGGER__')
    logger.setLevel(logging.INFO)
    if DEBUG:
        logger.setLevel(logging.DEBUG)
    loggerAddStreamHandle(logger)
    return logger

def loggerAddFileHandle(logger, filename):
    loggerRemoveFileHandlers(logger)
    handler = logging.FileHandler(filename)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    loggerAddStreamHandle(logger)
        
    # Set the custom exception handler to use this logger
    def log_uncaught_exceptions(exctype, value, tb):
        logger.critical("Uncaught exception", exc_info=(exctype, value, tb))
    sys.excepthook = log_uncaught_exceptions

# Function to add a stream handler to the logger
def loggerAddStreamHandle(logger):
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# Function to remove all handlers from the logger
def loggerRemoveFileHandlers(logger):
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
