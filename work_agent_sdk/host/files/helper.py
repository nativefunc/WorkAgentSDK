import errno
import hashlib
import json
import mimetypes
import os
import shutil
import stat as stat_module
import struct
import sys
import time
import uuid

BLOCK_SIZE = 512 * 1024
# When walking directories, the maximum number of times the same real directory is walked (once per link pointing to it), so nested links can't blow up the amount of walking
MAX_VISITS_PER_DIRECTORY = 10
TRANSFER_PREFIX = ".work-agent-transfer-"
# Framing of stdin when writing files in the sandbox: a data frame is b"D" + 4-byte length + data; the end frame is b"E" + 8-byte total size + 32-byte SHA-256
FRAME_DATA = b"D"
FRAME_END = b"E"

_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_BINARY = getattr(os, "O_BINARY", 0)


class Rules:
    def check_read(self, path):
        pass

    def check_write(self, path):
        pass

    def check_remove(self, path):
        pass

    def check_moved_tree(self, source, target):
        pass

    def visible(self, path):
        return True


UNRESTRICTED = Rules()


def _absolute(path):
    return os.path.abspath(os.path.expanduser(path))


def _real(path):
    return os.path.realpath(_absolute(path))


def _location(path):
    path = _absolute(path)
    return os.path.join(os.path.realpath(os.path.dirname(path)), os.path.basename(path))


def _key(path):
    path = os.path.normcase(os.path.normpath(path))
    return path.casefold() if sys.platform == "darwin" else path


def _inside(path, root):
    path, root = _key(path), _key(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _is_root(path):
    return os.path.dirname(path) == path


def _readable(rules, path):
    real = _real(path)
    rules.check_read(real)
    return real


def _writable(rules, path):
    real = _real(path)
    rules.check_write(real)
    return real


def _removable(rules, path, keep=()):
    target = _location(path)
    if _is_root(target) or any(_inside(_real(kept), target) for kept in keep):
        raise PermissionError(errno.EPERM, "Deleting or moving away is not allowed", path)

    rules.check_write(target)
    rules.check_remove(target)
    return target


def _transfer_file(rules, path, write):
    real = _writable(rules, path) if write else _readable(rules, path)
    if not os.path.basename(real).startswith(TRANSFER_PREFIX):
        raise PermissionError(errno.EPERM, "Chunked read/write is only for transfer files", path)
    return real


def _temporary(path):
    return os.path.join(os.path.dirname(path), f".{os.path.basename(path)}.work-agent-{uuid.uuid4().hex[:8]}")


def _info(path, real):
    result = os.stat(real)
    is_dir = stat_module.S_ISDIR(result.st_mode)
    name = os.path.basename(os.path.normpath(path)) or path
    return {
        "path": path,
        "name": name,
        "is_dir": is_dir,
        "size": 0 if is_dir else result.st_size,
        "modified": result.st_mtime,
        "mime": None if is_dir else mimetypes.guess_type(name)[0],
        "real_path": real,
    }


def opened_path(fd):
    try:
        if sys.platform.startswith("linux"):
            return os.readlink(f"/proc/self/fd/{fd}")
        if sys.platform == "darwin":
            import fcntl

            return fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024)).rstrip(b"\0").decode()
        if sys.platform == "win32":
            return _windows_opened_path(fd)
    except OSError:
        return None

    return None


def _windows_opened_path(fd):
    import ctypes
    import msvcrt
    from ctypes import wintypes

    function = ctypes.windll.kernel32.GetFinalPathNameByHandleW
    function.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    function.restype = wintypes.DWORD
    size = 32768
    buffer = ctypes.create_unicode_buffer(size)

    # 0: FILE_NAME_NORMALIZED and VOLUME_NAME_DOS, giving paths of the form \\?\C:\...
    length = function(msvcrt.get_osfhandle(fd), buffer, size, 0)
    if length == 0 or length >= size:
        return None

    path = buffer.value
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[8:]
    if path.startswith("\\\\?\\"):
        return path[4:]
    return path


def _check_opened(fd, path):
    # Prevent directories along the path from being swapped for links after the check
    actual = opened_path(fd)
    if actual is not None and _key(actual) != _key(path):
        raise PermissionError(errno.EPERM, "Replaced with another location after the check; operation refused", path)


# os.replace accepts src_dir_fd and dst_dir_fd but isn't listed in supports_dir_fd, so check via os.rename
_DIR_FD = all(function in os.supports_dir_fd for function in (os.open, os.unlink, os.rename, os.stat))


def _open_parent(path, create=False):
    parent = os.path.dirname(path)
    if create:
        os.makedirs(parent, exist_ok=True)
    if not _DIR_FD:
        return None

    fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        _check_opened(fd, parent)
    except BaseException:
        os.close(fd)
        raise

    return fd


def _close(*fds):
    for fd in fds:
        if fd is not None:
            os.close(fd)


def _open_at(path, flags, directory, mode=0o644):
    if directory is None:
        fd = os.open(path, flags, mode)
    else:
        fd = os.open(os.path.basename(path), flags, mode, dir_fd=directory)

    try:
        _check_opened(fd, path)
    except BaseException:
        os.close(fd)
        raise

    return fd


def _open_new(path, mode=0o644):
    directory = _open_parent(path)
    try:
        return _open_at(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _BINARY, directory, mode)
    finally:
        _close(directory)


# Transfer files only relay content between the backend and this machine and may contain secrets, so only the current local user can read and write them
TRANSFER_MODE = 0o600


def _existing_file_mode(path):
    try:
        info = os.lstat(path)
    except OSError:
        return None
    return stat_module.S_IMODE(info.st_mode) if stat_module.S_ISREG(info.st_mode) else None


def _open_existing(path, flags):
    return _open_at(path, flags | _NOFOLLOW | _BINARY, None)


def _write_all(fd, data):
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def _read_up_to(fd, size):
    data = bytearray()
    while len(data) < size:
        piece = os.read(fd, size - len(data))
        if not piece:
            break
        data += piece
    return bytes(data)


def _copy_content(source_fd, target_fd, digest=None, limit=None, name=""):
    total = 0
    while piece := os.read(source_fd, BLOCK_SIZE):
        total += len(piece)
        if limit is not None and total > limit:
            raise ValueError(f"{name} exceeds the limit of {limit} bytes")
        if digest is not None:
            digest.update(piece)
        if target_fd is not None:
            _write_all(target_fd, piece)

    return total


def _copy_file(source, target):
    inbound = _open_existing(source, os.O_RDONLY)
    try:
        outbound = _open_new(target)
        try:
            _copy_content(inbound, outbound)
            if hasattr(os, "fchmod"):
                os.fchmod(outbound, stat_module.S_IMODE(os.fstat(inbound).st_mode))
        finally:
            os.close(outbound)
    finally:
        os.close(inbound)


def _rename(source, target, source_dir, target_dir, exclusive):
    if source_dir is None or target_dir is None:
        if exclusive and os.path.lexists(target):
            raise FileExistsError(errno.EEXIST, "Target already exists", target)
        os.replace(source, target)
        return

    source_name, target_name = os.path.basename(source), os.path.basename(target)
    if exclusive and not stat_module.S_ISDIR(os.lstat(source).st_mode):
        # A hard link fails when the target exists, so "claiming the name" and "putting the file there" happen in the same step
        os.link(
            source_name,
            target_name,
            src_dir_fd=source_dir,
            dst_dir_fd=target_dir,
            follow_symlinks=False,
        )
        os.unlink(source_name, dir_fd=source_dir)
        return
    if exclusive and os.path.lexists(target):
        raise FileExistsError(errno.EEXIST, "Target already exists", target)

    os.replace(source_name, target_name, src_dir_fd=source_dir, dst_dir_fd=target_dir)


def _place(source, target, exclusive):
    # Across file systems, first copy to a temporary name in the target directory, then rename, so readers never see half the content
    source_dir = _open_parent(source)
    try:
        target_dir = _open_parent(target)
    except BaseException:
        _close(source_dir)
        raise

    try:
        try:
            _rename(source, target, source_dir, target_dir, exclusive)
            return
        except OSError as error:
            if error.errno != errno.EXDEV:
                raise
    finally:
        _close(source_dir, target_dir)

    partial = _temporary(target)
    try:
        if stat_module.S_ISDIR(os.lstat(source).st_mode):
            shutil.copytree(source, partial, symlinks=True)
        elif stat_module.S_ISLNK(os.lstat(source).st_mode):
            os.symlink(os.readlink(source), partial)
        else:
            _copy_file(source, partial)
        _place(partial, target, exclusive)
    except BaseException:
        _remove_at(partial)
        raise

    _remove_at(source)


def _remove_at(target):
    try:
        directory = _open_parent(target)
    except FileNotFoundError:
        return

    name = os.path.basename(target)
    try:
        if directory is None:
            if os.path.islink(target) or os.path.isfile(target):
                os.remove(target)
            elif os.path.isdir(target):
                shutil.rmtree(target)
            return

        try:
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            return

        if stat_module.S_ISDIR(info.st_mode):
            shutil.rmtree(name, dir_fd=directory)
        else:
            os.unlink(name, dir_fd=directory)
    finally:
        _close(directory)


def _walk(rules, root):
    entries = []
    visits = {}

    def walk(directory, relative, ancestors):
        for name in sorted(os.listdir(directory)):
            inner = os.path.join(relative, name) if relative else name
            real = os.path.realpath(os.path.join(directory, name))
            rules.check_read(real)
            is_dir = os.path.isdir(real)
            entries.append((inner, real, is_dir))

            if not is_dir:
                continue

            key = _key(real)
            if key in ancestors:
                raise PermissionError(errno.EPERM, f"{inner} links back to its own parent directory (forms a cycle)")

            visits[key] = visits.get(key, 0) + 1
            if visits[key] > MAX_VISITS_PER_DIRECTORY:
                raise PermissionError(errno.EPERM, f"The directory {inner} points to is linked more than {MAX_VISITS_PER_DIRECTORY} times")

            walk(real, inner, ancestors | {key})

    walk(root, "", frozenset({_key(root)}))
    return entries


def _check_file(path, real):
    if os.path.isdir(real):
        raise IsADirectoryError(errno.EISDIR, "Is a directory, not a file", path)


def stat(rules, path):
    return _info(_absolute(path), _readable(rules, path))


def list_dir(rules, path):
    real = _readable(rules, path)
    if not os.path.isdir(real):
        raise NotADirectoryError(errno.ENOTDIR, "Not a directory", path)

    base = _absolute(path)
    entries = []
    for name in sorted(os.listdir(real)):
        try:
            entry = os.path.realpath(os.path.join(real, name))
            if rules.visible(entry):
                entries.append(_info(os.path.join(base, name), entry))
        except OSError:
            continue

    return entries


def make_dir(rules, path):
    os.makedirs(_writable(rules, path), exist_ok=True)


def remove(rules, path):
    target = _location(path)
    if not os.path.lexists(target):
        return

    _remove_at(_removable(rules, target))


def delete(rules, path, directory, recursive, keep=()):
    target = _removable(rules, path, keep)
    is_dir = stat_module.S_ISDIR(os.lstat(target).st_mode)
    if directory:
        if not is_dir:
            raise NotADirectoryError(errno.ENOTDIR, "Not a directory", path)
        if not recursive and os.listdir(target):
            raise OSError(errno.ENOTEMPTY, f"Directory not empty: {path}; to delete the whole directory, pass recursive=True")
    elif is_dir:
        raise IsADirectoryError(errno.EISDIR, "Is a directory; use delete_dir", path)

    _remove_at(target)


def move(rules, source, target, keep=()):
    origin = _removable(rules, source, keep)
    os.lstat(origin)
    destination = _location(target)
    rules.check_write(destination)
    rules.check_moved_tree(origin, destination)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    _place(origin, destination, exclusive=True)


def copy(rules, source, target):
    origin = _readable(rules, source)
    destination = _location(target)
    rules.check_write(destination)

    if os.path.lexists(destination):
        raise FileExistsError(errno.EEXIST, "Target already exists", target)

    entries = _walk(rules, origin) if os.path.isdir(origin) else None
    for relative, _, _ in entries or ():
        rules.check_write(os.path.join(destination, relative))

    os.makedirs(os.path.dirname(destination), exist_ok=True)
    partial = _temporary(destination)
    try:
        if entries is None:
            _copy_file(origin, partial)
        else:
            os.mkdir(partial)
            for relative, real, is_dir in entries:
                inner = os.path.join(partial, relative)
                if is_dir:
                    os.mkdir(inner)
                else:
                    _copy_file(real, inner)

        _place(partial, destination, exclusive=True)
    except BaseException:
        _remove_at(partial)
        raise


def readable(rules, path):
    real = _readable(rules, path)
    if not os.path.isdir(real):
        os.close(_open_existing(real, os.O_RDONLY))
        return [[".", real]]

    found = []
    for relative, entry, is_dir in _walk(rules, real):
        if not is_dir:
            os.close(_open_existing(entry, os.O_RDONLY))
            found.append([relative, entry])

    return found


def snapshot(rules, source, staging, max_size=None):
    origin = _readable(rules, source)
    _check_file(source, origin)
    target = _transfer_file(rules, staging, write=True)
    inbound = _open_existing(origin, os.O_RDONLY)
    try:
        size = os.fstat(inbound).st_size
        if max_size is not None and size > max_size:
            raise ValueError(f"{source} is {size} bytes, exceeding the limit of {max_size} bytes")

        os.makedirs(os.path.dirname(target), exist_ok=True)
        outbound = _open_new(target, TRANSFER_MODE)
        digest = hashlib.sha256()
        try:
            total = _copy_content(inbound, outbound, digest, max_size, source)
        except BaseException:
            os.close(outbound)
            _remove_at(target)
            raise

        os.close(outbound)
    finally:
        os.close(inbound)

    return {"size": total, "sha256": digest.hexdigest()}


def read_block(rules, path, offset, size):
    fd = _open_existing(_transfer_file(rules, path, write=False), os.O_RDONLY)
    try:
        os.lseek(fd, offset, os.SEEK_SET)
        return _read_up_to(fd, size)
    finally:
        os.close(fd)


def write_block(rules, path, offset, data):
    real = _transfer_file(rules, path, write=True)
    if offset == 0:
        os.makedirs(os.path.dirname(real), exist_ok=True)
        fd = _open_new(real, TRANSFER_MODE)
    else:
        fd = _open_existing(real, os.O_WRONLY)

    try:
        written = os.fstat(fd).st_size
        if written != offset:
            raise OSError(errno.EIO, f"Transfer file already has {written} bytes, which doesn't match write position {offset}", path)

        os.lseek(fd, offset, os.SEEK_SET)
        _write_all(fd, data)
    finally:
        os.close(fd)


def _publish(source, target, path, size, sha256, total, digest, executable):
    # When overwriting an existing file, keep its original permissions instead of loosening 0600 to 0644
    if total != size or digest != sha256:
        raise OSError(errno.EIO, f"Written content failed verification: received {total} bytes, expected {size} bytes", path)
    if os.path.isdir(target):
        raise IsADirectoryError(errno.EISDIR, "Is a directory, not a file", path)

    existing = _existing_file_mode(target)
    if executable:
        mode = 0o755
    elif existing is not None:
        mode = existing
    else:
        mode = 0o644
    os.chmod(source, mode)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    _place(source, target, exclusive=False)
    return _info(_absolute(path), target)


def commit(rules, staging, target, size, sha256, executable=False):
    source = _transfer_file(rules, staging, write=True)
    destination = _writable(rules, target)
    fd = _open_existing(source, os.O_RDONLY)
    digest = hashlib.sha256()
    try:
        total = _copy_content(fd, None, digest)
    finally:
        os.close(fd)

    return _publish(source, destination, target, size, sha256, total, digest.hexdigest(), executable)


def read(rules, path, max_size=None, output=None):
    real = _readable(rules, path)
    _check_file(path, real)
    output = output or sys.stdout.buffer
    fd = _open_existing(real, os.O_RDONLY)
    digest = hashlib.sha256()
    total = 0
    try:
        size = os.fstat(fd).st_size
        if max_size is not None and size > max_size:
            raise ValueError(f"{path} is {size} bytes, exceeding the limit of {max_size} bytes")

        while piece := os.read(fd, BLOCK_SIZE):
            total += len(piece)
            if max_size is not None and total > max_size:
                raise ValueError(f"{path} exceeds the limit of {max_size} bytes")

            digest.update(piece)
            output.write(piece)

        output.flush()
    finally:
        os.close(fd)

    return {"size": total, "sha256": digest.hexdigest()}


def _exactly(source, size):
    data = source.read(size)
    if len(data) != size:
        raise OSError(errno.EIO, "Data was interrupted before the transfer completed")
    return data


def write(rules, path, staging_dir, executable=False, source=None):
    destination = _writable(rules, path)
    source = source or sys.stdin.buffer
    staging = _transfer_file(rules, os.path.join(staging_dir, TRANSFER_PREFIX + uuid.uuid4().hex), write=True)
    os.makedirs(os.path.dirname(staging), exist_ok=True)
    fd = _open_new(staging, TRANSFER_MODE)
    digest = hashlib.sha256()
    total = 0
    try:
        try:
            while True:
                kind = _exactly(source, 1)
                if kind == FRAME_END:
                    size, sha256 = struct.unpack(">Q32s", _exactly(source, 40))
                    break
                if kind != FRAME_DATA:
                    raise OSError(errno.EIO, "Malformed data")

                (length,) = struct.unpack(">I", _exactly(source, 4))
                piece = _exactly(source, length)
                digest.update(piece)
                total += len(piece)
                _write_all(fd, piece)
        finally:
            os.close(fd)

        return _publish(staging, destination, path, size, sha256.hex(), total, digest.hexdigest(), executable)
    except BaseException:
        _remove_at(staging)
        raise


def ensure_private_dir(path):
    # It holds transfer files and browser sign-in state, which other local users shouldn't be able to read
    os.makedirs(path, mode=0o700, exist_ok=True)

    if os.name != "posix":
        return

    info = os.stat(path)
    if info.st_uid == os.getuid() and stat_module.S_IMODE(info.st_mode) != 0o700:
        os.chmod(path, 0o700)


def clean_transfers(tmp_root, max_age=3600):
    now = time.time()

    try:
        children = os.listdir(tmp_root)
    except OSError:
        return

    for child in children:
        directory = os.path.join(tmp_root, child)
        if os.path.islink(directory) or not os.path.isdir(directory):
            continue

        try:
            names = os.listdir(directory)
        except OSError:
            continue

        for name in names:
            if not name.startswith(TRANSFER_PREFIX):
                continue
            path = os.path.join(directory, name)
            try:
                if now - os.lstat(path).st_mtime > max_age:
                    _remove_at(path)
            except OSError:
                continue


OPERATIONS = {
    "stat": stat,
    "list": list_dir,
    "make_dir": make_dir,
    "remove": remove,
    "delete": delete,
    "move": move,
    "copy": copy,
    "readable": readable,
    "snapshot": snapshot,
    "commit": commit,
}


def run_op(op, arguments, rules=UNRESTRICTED):
    operation = OPERATIONS.get(op)
    if operation is None:
        raise ValueError(f"Unknown file operation: {op}")
    return operation(rules, **arguments)


def error_info(error):
    base = next(cls for cls in type(error).__mro__ if cls.__module__ == "builtins")
    result = {"type": base.__name__, "message": str(error)}
    if isinstance(error, OSError):
        number = error.errno if isinstance(error.errno, int) else None
        result["errno"] = errno.errorcode.get(number) if number is not None else None
        if error.filename is not None and error.strerror:
            result["message"] = f"{error.strerror}: {error.filename}"

    return result


def main():
    try:
        request = json.loads(sys.argv[1])
        op = request.pop("op")
        if op == "read":
            summary = read(UNRESTRICTED, **request)
            sys.stderr.write("\n" + json.dumps(summary) + "\n")
            sys.stderr.flush()
            return

        result = write(UNRESTRICTED, **request) if op == "write" else run_op(op, request)
        if result is not None:
            sys.stdout.write(json.dumps(result, ensure_ascii=False))
            sys.stdout.flush()
    except Exception as error:  # noqa: BLE001 - encode any error and send it back
        sys.stderr.write("\n" + json.dumps(error_info(error), ensure_ascii=False) + "\n")
        sys.stderr.flush()
        sys.exit(1)


if __name__ == "__main__":
    main()
