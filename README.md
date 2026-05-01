# Compact OwnCloud/NextCloud WebDAV client
A simple and compact WebDAV client written in Python 3.

### Features
- All WebDAV operations supported
- Flexible listing, with optional recursion
- Proper error reporting
- Flexible instance targeting

### Requirements
- Python 3.12+
- Various packages, including `requests`

### Installation
To install the repository as a package run

```sh
pip3 install -e .
```

Optionally, create a separate virtual environment and activate it.

Install the required packages using the `requirements.txt` file:

```sh
pip3 install -r requirements.txt
```

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
In the following examples it is assumed the package is installed on the system.

General syntax:

```sh
dav <operation> [options] <source> [target]
```

where `operation` is one of the valid operations available, `source` is the path to process and the optional `target` is the target path.

The optional `options` can be found through:

```sh
dav --help
```

This list all available operations and options.

You can find more detailed information per operation through:

```sh
dav <operation> --help
```

### Examples
- List contents of your root folder:

```sh
dav list /
```

- List contents of your folder 'my/excellent/folder', display subfolders first, show a summary at the end, sort alphabetically, show human-readable sizes:

```sh
dav list my/excellent/folder -tuh --sort
```

- Create a folder 'folder' in root:

```sh
dav mkcol folder
```

- Delete a folder 'folder' and auto-confirm:

```sh
dav delete folder -y
```

- Rename a file `test.dat` stored in a folder `test` to `test.txt`:

```sh
dav move test/test.dat test/test.txt
```

- Move a file `wrong.dat` stored in a folder `data` to the root folder and rename it to `right.dat`:

```sh
dav move data/wrong.dat /right.dat
```

- Copy a file `test.dat` stored in a folder `test` to `test.txt`:

```sh
dav copy test/test.dat test/test.txt
```

- Download a file `test/test.txt`

```sh
dav download test/test.txt
```

- Upload a file `test.txt` to folder `test`:

```sh
dav upload test/test.txt test.txt
```
