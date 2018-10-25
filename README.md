# Compact OwnCloud/NextCloud WebDAV client
A simple and compact WebDAV client written in Python 3.

### Features
- All WebDAV operations supported
- Flexible listing, with optional recursion
- Proper error reporting
- Flexible instance targetting

### Requirements
- Python 3.6+
- Various packages, including `requests`

### Configuration
You need a configuration file in JSON format in order to allow the client to contact your WebDAV server. It must contain the following elements:

```
{
    "hostname": "",     ---> FQDN of host for WebDAV interaction
    "endpoint": "",     ---> WebDAV endpoint at host
    "user": "",         ---> User name
    "token": ""         ---> Your token
}
```

You can find the endpoint and credentials in the settings of your WebDAV installation, e.g. OwnCloud or NextCloud.

A stub configuration file is provided as `credentials.stub.json`. Copy it and fill in your values.

### How to run
General syntax:

```sh
dav.py <operation> [options] <source> [target]
```

where `operation` is one of the valid operations available, `source` is the path to process and the optional `target` is the target path.

The optional `options` can be found through:

```sh
dav.py --help
```

This list all available operations and options.

You can find more detailed information per operation through:

```sh
dav.py <operation> --help
```

### Examples
- List contents of your root folder:

```sh
dav.py list /
```

- List contents of your folder 'my/excellent/folder', display subfolders first, show a summary at the end, sort alphabetically, show human-readable sizes:

```sh
dav.py list my/excellent/folder -tuh --sort
```

- Create a folder 'folder' in root:

```sh
dav.py mkcol folder
```

- Delete a folder 'folder' and auto-confirm:

```sh
dav.py delete folder -y
```

- Rename a file `test.dat` stored in a folder `test` to `test.txt`:

```sh
dav.py move test/test.dat test/test.txt
```

- Move a file `wrong.dat` stored in a folder `data` to the root folder and rename it to `right.dat`:

```sh
dav.py move data/wrong.dat /right.dat
```

- Copy a file `test.dat` stored in a folder `test` to `test.txt`:

```sh
dav.py copy test/test.dat test/test.txt
```

- Download a file `test/test.txt`

```sh
dav.py download test/test.txt
```

- Upload a file `test.txt` to folder `test`:

```sh
dav.py upload test/test.txt test.txt
```
