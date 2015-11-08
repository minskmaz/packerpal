# packerpal
subprocess pipes play nice and react to packer (verbose) build command by way of stdout/stderr stream

Requirements:

* 10 minutes (read the code)
* 1 minute (set 8 variables)
* 4 minutes (your docker image(s) is/are ready)

Background:

* [async pipe reading](http://stefaanlippens.net/python-asynchronous-subprocess-pipe-reading)
* [packer build command](https://www.packer.io/docs/command-line/build.html)
* [python's subprocess module](https://pymotw.com/2/subprocess/)
* [python's threading module](https://pymotw.com/2/threading/)
* [python's Queue module](https://pymotw.com/2/Queue/index.html#module-Queue)

### you will need to write one little order.json file looks like this:

	['my_packer_file.json', 'some_other_packer_file.json']