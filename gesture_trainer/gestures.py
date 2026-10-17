"""Gerenciamento de gestos (§17): visualizar/adicionar/renomear/excluir,
re-treinar, exportar/importar, redefinir — sobre o banco de dados.
"""

import shutil

from .config import BOTH_HANDS_GESTURES, DEFAULT_GESTURES


def registry(dataset):
    """{hand: [(id, label, dynamic, n)]} a partir do disco + padrões."""
    reg = {}
    for hand, table in (("right", DEFAULT_GESTURES), ("left", DEFAULT_GESTURES),
                        ("both", BOTH_HANDS_GESTURES)):
        rows = []
        for gid, label, dyn in table:
            rows.append((gid, label, dyn, dataset.count(hand, gid)))
        # gestos custom (pastas sem registro padrão)
        try:
            known = {g for g, _, _ in table}
            for d in sorted((dataset.root / hand).iterdir()):
                if d.is_dir() and d.name not in known:
                    rows.append((d.name, d.name.upper(), False,
                                 dataset.count(hand, d.name)))
        except OSError:
            pass
        reg[hand] = rows
    return reg


def add_gesture(dataset, hand, gid, dynamic=False):
    dataset._dir(hand, gid)
    return gid


def rename_gesture(dataset, hand, old, new):
    src, dst = dataset._dir(hand, old), dataset.root / hand / new
    if src.exists() and not dst.exists():
        src.rename(dst)
        return True
    return False


def delete_gesture(dataset, hand, gid):
    shutil.rmtree(dataset._dir(hand, gid), ignore_errors=True)


def retrain_gesture(dataset, hand, gid):
    dataset.clear(hand, gid)


def export_model(src, dst):
    shutil.copyfile(src, dst)


def import_model(src, dst):
    shutil.copyfile(src, dst)
