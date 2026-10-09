# Provenance and third-party notes

## AgentSearch 0.1.0

AgentSearch is an independent implementation created for James Paul Jackson. Its source code and documentation are provided under the [MIT license](LICENSE). The working name is local to this package; this delivery does not establish a published package name or trademark clearance.

## FSearch inspiration

The starting idea was prompted by [noahdunnagan/fsearch](https://github.com/noahdunnagan/fsearch), whose repository describes a macOS search engine with fuzzy filename search, an indexed content search, and structured interfaces. The upstream repository identifies its license as MIT. Its [license file](https://github.com/noahdunnagan/fsearch/blob/main/LICENSE) is the authoritative upstream notice.

No FSearch source code is included in this package. This is not an upstream release, an affiliated project, or a drop-in replacement for its CLI or Rust API. The acknowledgment identifies the inspiration; it does not transfer the upstream author's benchmark claims to AgentSearch.

## Runtime and packaging

Normal execution uses Python's standard library, including its `sqlite3` module. The interpreter must provide SQLite FTS5 with the trigram tokenizer. Python and SQLite retain their own licensing terms; neither runtime is redistributed in this source package.

An optional Python package build uses setuptools, declared as a build dependency in `pyproject.toml`. Running `python -m agentsearch` from this folder requires no pip installation or third-party Python dependencies.

## Documentation references

Official implementation references used for the planned Windows backend:

- [Microsoft: ReadDirectoryChangesW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-readdirectorychangesw)
- [Microsoft: Change journals](https://learn.microsoft.com/en-us/windows/win32/fileio/change-journals)

These references describe possible future acceleration. AgentSearch 0.1.0 uses directory enumeration and foreground polling.
