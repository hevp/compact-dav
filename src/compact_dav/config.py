import argparse
import copy


class ConfigMeta(type):
    def __getitem__(cls, key: str) -> object:
        return cls.data[key]

    def __setitem__(cls, key: str, value: object) -> None:
        cls.data[key] = value

    def __contains__(cls, key: str) -> bool:
        return key in cls.data

    def update(cls, d: dict[str, object]) -> None:
        cls.data.update(d)


class Config(metaclass=ConfigMeta):
    data = {}

    @staticmethod
    def get(key: str, default: object) -> object:
        return Config.data.get(key, default)

    @staticmethod
    def set(ns: argparse.Namespace, defaults: dict[str, object]) -> None:
        skip = {"operation"} | {f"arg{i}" for i in range(1, 10)}
        opts = {k.replace("_", "-"): v for k, v in vars(ns).items() if k not in skip}
        Config.data = copy.deepcopy(defaults)
        Config.data.update(opts)
        Config.data["defaults"] = copy.deepcopy(defaults)
        Config.data["credentials"] = None
