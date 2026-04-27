import argparse
import copy


class ConfigMeta(type):
    def __getitem__(cls, key):
        return cls.data[key]

    def __setitem__(cls, key, value):
        cls.data[key] = value

    def __contains__(cls, key):
        return key in cls.data

    def update(cls, d: dict):
        cls.data.update(d)


class Config(metaclass=ConfigMeta):
    data = {}

    @staticmethod
    def get(key, default):
        return Config.data.get(key, default)

    @staticmethod
    def set(ns: argparse.Namespace, defaults: dict):
        skip = {"operation"} | {f"arg{i}" for i in range(1, 10)}
        opts = {k.replace("_", "-"): v for k, v in vars(ns).items() if k not in skip}
        Config.data = copy.deepcopy(defaults)
        Config.data.update(opts)
        Config.data["defaults"] = copy.deepcopy(defaults)
        Config.data["credentials"] = None
