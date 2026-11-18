"""Small pure edit adapter and exclusive JSON writer; no bpy or scene writes."""
import copy
import json
import os
from pathlib import Path
import stat
from . import candidate_model as model


def edited_variant(document, name, edit):
    doc = model.validate_document(document)
    if type(edit) is not dict:
        raise ValueError('Edit must be an object')
    kind = edit.get('op')
    rows = doc['rows']
    indices = {row['name']: i for i, row in enumerate(rows)}
    allowed = set()
    if kind == 'copy':
        if set(edit) != {'op'}:
            raise ValueError('COPY has no edit fields')
        operations = copy.deepcopy(doc['operations'])
    else:
        if kind == 'choose_camera':
            if set(edit) != {'op', 'shot', 'camera'} or type(edit['shot']) is not str or edit['shot'] not in indices:
                raise ValueError('Choose an existing shot')
            if type(edit['camera']) is not str or edit['camera'] not in doc['catalog']:
                raise ValueError('Choose an existing source camera')
            key = lambda op: (op.get('op'), op.get('shot'))
            allowed.add((indices[edit['shot']], 'camera'))
        elif kind == 'move_cut':
            if set(edit) != {'op', 'left', 'right', 'left_last'} or type(edit['left']) is not str or type(edit['right']) is not str:
                raise ValueError('Invalid cut edit')
            left, right = indices.get(edit['left']), indices.get(edit['right'])
            if left is None or right != left + 1:
                raise ValueError('Choose an ordered adjacent cut')
            if type(edit['left_last']) is not int or not rows[left]['first'] <= edit['left_last'] < rows[right]['last']:
                raise ValueError('Cut must leave both current candidate shots nonempty')
            key = lambda op: (op.get('op'), op.get('left'), op.get('right'))
            allowed.update(((left, 'last'), (right, 'first')))
        else:
            raise ValueError('Unknown edit operation')
        operations = copy.deepcopy(doc['operations'])
        matches = [i for i, op in enumerate(operations) if key(op) == key(edit)]
        if len(matches) > 1:
            raise ValueError('Ambiguous existing operation target')
        if matches:
            operations[matches[0]] = copy.deepcopy(edit)
        else:
            operations.append(copy.deepcopy(edit))
    result = model.variant(doc, name, operations)
    for index, (before, after) in enumerate(zip(rows, result['rows'])):
        for field in before:
            if before[field] != after[field] and (index, field) not in allowed:
                raise ValueError('Edit would change an untargeted field')
    return result


class OutputIncomplete(RuntimeError):
    pass


def save_new_json(path, document, forbidden_paths=()):
    doc = model.validate_document(document)
    raw = (json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')
    # The strict reader's size budget also applies to pretty-printed output.
    if len(raw) > model.MAX_BYTES:
        raise ValueError('Encoded candidate exceeds the JSON size limit')
    p = Path(path)
    if not p.is_absolute() or '..' in p.parts or p.suffix.lower() != '.json':
        raise ValueError('Choose a new absolute .json output path')
    for q in p.parents:
        if q.is_symlink() or not q.is_dir():
            raise ValueError('Output parents must be existing real directories')
    if str(p) in {str(Path(x)) for x in forbidden_paths}:
        raise ValueError('The original input path cannot be an output')
    if p.exists() or p.is_symlink():
        raise ValueError('Output already exists; choose a new filename')
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(p, flags, 0o600)
    created_identity = None
    try:
        info = os.fstat(fd)
        created_identity = (info.st_dev, info.st_ino)
        if not stat.S_ISREG(info.st_mode):
            raise RuntimeError('Created target is not regular')
        with os.fdopen(fd, 'wb') as stream:
            fd = None
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        info = p.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != created_identity:
            raise RuntimeError('Output identity changed before verification')
        read_fd = os.open(p, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        try:
            opened = os.fstat(read_fd)
            if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != created_identity:
                raise RuntimeError('Readback target identity differs')
            with os.fdopen(read_fd, 'rb') as stream:
                read_fd = None
                observed = stream.read(model.MAX_BYTES + 1)
        finally:
            if read_fd is not None: os.close(read_fd)
        parsed = model.load_json(observed)
        if observed != raw or parsed != doc or parsed['content_sha256'] != doc['content_sha256']:
            raise RuntimeError('Output readback differs')
        return {'file': str(p), 'content_sha256': doc['content_sha256'], 'bytes': len(raw)}
    except Exception as exc:
        raise OutputIncomplete('Output incomplete or uncertain at ' + str(p) + '. Inspect it; it was not removed. ' + str(exc)) from exc
    finally:
        if fd is not None:
            os.close(fd)
