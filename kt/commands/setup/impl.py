import logging

from kt.ktlib.config import Config
from kt.ktlib.kernels import KernelsInfo
from kt.ktlib.repo import RepoInfoException


def main():
    config = Config.load()

    # create working dir if it does not exist
    config.base_path.mkdir(parents=True, exist_ok=True)

    repos = KernelsInfo.from_yaml(config=config).repos
    for repo in repos.values():
        try:
            repo.setup_repo()
        except RepoInfoException as e:
            logging.error(e, exc_info=True)
