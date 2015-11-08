
import ConfigParser
import json
import os
import subprocess
from subprocess import Popen, PIPE
import Queue
import threading
import time

#----------------------------------------------------------------------------#
#--- CONFIGURATION PARSER ---------------------------------------------------#
#----------------------------------------------------------------------------#

class Config(object):
    def __init__(self, filename):
        super(Config, self).__init__()
        self._data = {}
        config = ConfigParser.ConfigParser()
        config.read(filename)
        for section in config.sections():
            self._data[section] = {}
            for option in config.options(section):
                self._data[section][option] = \
                    config.get(section, option)

    def keys(self):
        return self._data.keys()

    def __setitem__(self, key, val):
        self._data[key] = val

    def __getitem__(self, key):
        return self._data[key]

    def __repr__(self):
        return self._data

#----------------------------------------------------------------------------#
#--- ASYNC FILE READER ------------------------------------------------------#
#----------------------------------------------------------------------------#

class AsynchronousFileReader(threading.Thread):
    def __init__(self, fd, queue):
        assert isinstance(queue, Queue.Queue)
        assert callable(fd.readline)
        threading.Thread.__init__(self)
        self._fd = fd
        self._queue = queue
 
    def run(self):
        for line in iter(self._fd.readline, ''):
            self._queue.put(line)
 
    def eof(self):
        return not self.is_alive() and self._queue.empty()

#----------------------------------------------------------------------------#
#--- PACKER WRAPPER CLASS ---------------------------------------------------#
#----------------------------------------------------------------------------#

class Packer(object):

    def get_packer_order(self, machines_path, order=None):
        if not order:
            order_file = \
                open(os.path.join(machines_path, 'order.json'), 'r')
            return json.loads(order_file.read())
        return order
    
    def get_packer_abs_paths(self, machines_path):
        if os.path.exists(machines_path):
            os.chdir(machines_path)
            order = self.get_packer_order(machines_path)
            res = {}
            for filename in order:
                abs_path = os.path.join(machines_path, filename)
                if os.path.exists(abs_path):
                    res[filename] = abs_path
            res['order'] = order
            return res
    
    ### reactors to test for text slugs appearing in stdout/stderr

    def doNothing(self, line, **kwargs):
        pass
    
    def imported_id_action(self, line, **kwargs):
        if kwargs.get('stdout'):
            image_id = repr(line).split(': ')[-1][:11]
            print "##############################"
            print "CREATED ",image_id
            print "##############################"
    
    def line_processor(self, line, stdout=False, stderr=False):
        doNothing = self.doNothing
        slug_action_mappings = {
            '==>':doNothing,
            'Starting container with args':doNothing,
            'Builds finished but no artifacts were created':doNothing,
            'Run command:':doNothing,
            'Provisioning with shell script:':doNothing,
            'Fetched':doNothing,
            'Imported ID':self.imported_id_action,
        }
        slugs = slug_action_mappings.keys()
    
        found = False
        for slug in slugs:
            if not found:
                if slug in line:
                    if stdout:
                        print "[ STDOUT ] ", line
                        slug_action_mappings[slug](line, stdout=True)
                    if stderr:
                        print "[ STDERR ] ", line
                        slug_action_mappings[slug](line, stderr=True)
                    found = True
        #print repr(line)
    
    ### subprocess with async unicorns

    def execute(self, cmd=['true'], env={}, cwd="/tmp"):
        proc = subprocess.Popen(cmd, 
            shell=False, 
            stdout=PIPE, 
            stderr=PIPE, 
            env=env, 
            cwd=cwd
        )
        stdout_queue = Queue.Queue()
        stdout_reader = \
            AsynchronousFileReader(proc.stdout, stdout_queue)
        stdout_reader.start()
        stderr_queue = Queue.Queue()
        stderr_reader = \
            AsynchronousFileReader(proc.stderr, stderr_queue)
        stderr_reader.start()
        while not stdout_reader.eof() or not stderr_reader.eof():
            while not stdout_queue.empty():
                line = stdout_queue.get()
                self.line_processor(line, stdout=True)
            while not stderr_queue.empty():
                line = stderr_queue.get()
                self.line_processor(line, stderr=True)
            time.sleep(.2)
        stdout_reader.join()
        stderr_reader.join()
        proc.stdout.close()
        proc.stderr.close()
    
    
    def build_environ(self, env_variables):
        required = [
            'DOCKER_HOST', 'DOCKER_TLS_VERIFY', 
            'DOCKER_OPTS', 'DOCKER_MACHINE_NAME', 
            'DOCKER_CERT_PATH', "TMPDIR", "PACKER_LOG"
        ]
        env = {}
        # load existing env veriables
        for x in os.environ.keys():
            if x in required:
                env[x]=os.environ[x]
        # load passed in env veriables
        for x in env_variables.keys():
            env[x.upper()]=env_variables[x]
        return env

    ### yes, we write out shell scripts then run them

    def build_packer_script(self, dynamic_exec_path, machines_path, packer_exec_path, packer_vars, config_path):
        script = """
        #!/bin/bash
        eval "$(docker-machine env default)";
        export PACKER_LOG=1;
        export TMPDIR=~/tmp;
        cd %s;
        %s build %s %s;
        """%(machines_path, packer_exec_path, packer_vars, config_path)
        name = config_path.split('/')[-1].split('.')[0]
        suffix = name+'_'+str(time.time())+'.sh'
        script_path = os.path.join(dynamic_exec_path, suffix)
        script = '\n'.join([x.strip() for x in script.split('\n')])
        with open(script_path, 'w') as f:
            f.write(script)
        return script_path
    
    def build_packer_var(self, key, val):
        return "-var '%s=%s' "%(key, val)
    
    def build_packer_vars(self, packer_var_mappings):
        tmp = ''
        for key in packer_var_mappings.keys():
            val = packer_var_mappings[key]
            tmp+=self.build_packer_var(key, val)
        return tmp.strip()
    
    def build(self, config):
        packer = Packer()
        env = config['env']
        for key in env:
            os.environ[key] = env[key]
        packer_exec_path = config['paths']['packer_exec_path']
        dynamic_exec_path = config['paths']['dynamic_exec_path']
        machines_path = config['paths']['machines_path']
        dockers_dir = config['paths']['dockers_dir']
        packer_var_mappings = config['packer_vars']

        packers = self.get_packer_abs_paths(machines_path)
        for name in packers.get('order'):
            config_abs_path = str(os.path.join(machines_path, name))
            script_path = self.build_packer_script(
                dynamic_exec_path,
                machines_path,
                packer_exec_path,
                self.build_packer_vars(packer_var_mappings), 
                config_abs_path
            )
            cmd = ['/bin/bash', script_path]
            self.execute(cmd=cmd, env=self.build_environ(env), cwd=dockers_dir)

if __name__ == '__main__':
    config = Config('packit.ini')
    packer = Packer()
    packer.build()
