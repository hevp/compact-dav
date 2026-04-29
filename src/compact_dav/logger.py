import logging
import sys
from .config import Config

class Logger:
    _COLORS = {
        logging.DEBUG:   '\x1b[32m',
        logging.INFO:    '\x1b[33m',
        logging.WARNING: '\x1b[96m',
        logging.ERROR:   '\x1b[31m',
    }
    _LABELS = {
        logging.DEBUG:   lambda r: f"% {r.funcName}()",
        logging.INFO:    lambda r: f"% {r.funcName}()",
        logging.WARNING: lambda _: "warning",
        logging.ERROR:   lambda _: "error",
    }

    _logger: logging.Logger
    _out_handler: logging.StreamHandler

    class _Formatter(logging.Formatter):
        def format(self, record):
            color = Logger._COLORS.get(record.levelno, '\x1b[0m')
            label = Logger._LABELS.get(
                record.levelno,
                lambda r: getattr(r, 'label', 'note'),
            )(record)
            msg = record.getMessage()
            if Config.get('no-colors', False):
                return f"{label}: {msg}"
            return f"{color}{label}:\x1b[0m {msg}"

    @classmethod
    def init(cls):
        cls._logger = logging.getLogger("compact_dav")
        cls._logger.propagate = False

        fmt = cls._Formatter()

        cls._out_handler = logging.StreamHandler(sys.stdout)
        cls._out_handler.addFilter(lambda r: r.levelno < logging.ERROR)
        cls._out_handler.setLevel(logging.INFO)
        cls._out_handler.setFormatter(fmt)

        err = logging.StreamHandler(sys.stderr)
        err.setLevel(logging.ERROR)
        err.setFormatter(fmt)

        cls._logger.addHandler(cls._out_handler)
        cls._logger.addHandler(err)
        cls._logger.setLevel(logging.DEBUG)

    @classmethod
    def configure(cls):
        if Config.get('debug', False):
            level = logging.DEBUG
        elif Config.get('quiet', False):
            level = logging.ERROR
        else:
            level = logging.INFO
        cls._out_handler.setLevel(level)

    @classmethod
    def log(cls, level, msg, ret=True, **kwargs):
        cls._logger.log(level, msg, stacklevel=3, **kwargs)
        return ret


def error(msg, code=None, ret=False):
    Logger.log(logging.ERROR, msg)
    if code is not None:
        sys.exit(code)
    return ret


def warning(msg, ret=False):
    return Logger.log(logging.WARNING, msg, ret)


def verbose(msg, ret=True):
    if Config.get('verbose', False):
        Logger.log(logging.INFO, msg, extra={'label': 'verbose'})
    return ret


def debug(msg, force=False, ret=True):
    return Logger.log(logging.INFO if force else logging.DEBUG, msg, ret)
