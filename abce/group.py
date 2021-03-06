from builtins import list
from collections import defaultdict
from pprint import pprint
from functools import partial


def get_methods(a_class):
    return [method for method in a_class.__dict__.keys() if
            callable(getattr(a_class, method)) and not
            method.startswith('_') and method != 'init']


class Group(object):
    def __init__(self, sim, groups, agent_class=None):
        self.sim = sim
        self.num_managers = sim.processes
        self._processor_groups = sim._processor_groups
        self.groups = groups
        self.do = (self.execute_parallel
                   if sim.processes > 1
                   else self.execute_serial)

        self.agent_class = agent_class
        methods = get_methods(agent_class)
        for base in agent_class.__bases__:
            methods += get_methods(base)
        for method in methods:
            if method not in ['panel', 'aggregate']:
                setattr(self, method,
                    eval('lambda self=self, *argc, **kw: self.do("%s")' % method))

    def __add__(self, g):
        return Group(self.sim, self.groups + g.groups, self.agent_class)

    def __radd__(self, g):
        if isinstance(g, Group):
            return __add__(g)
        else:
            return self

    def execute_serial(self, command):
        self.sim.messagess[-2].clear()
        out_messages = self._processor_groups[0].execute(
            self.groups, command, [])
        for pgid, messages in enumerate(out_messages):
            self.sim.messagess[pgid].extend(messages)
        return self.sim.messagess[-2]

    def execute_parallel(self, command):
        self.sim.messagess[-2].clear()
        parameters = ((pg, self.groups, command, self.sim.messagess[pgid])
                      for pgid, pg in enumerate(
            self._processor_groups))
        out = self.sim.pool.map(execute_wrapper, parameters, chunksize=1)
        for pgid in range(self.num_managers):
            self.sim.messagess[pgid].clear()
        for out_messages in out:
            for pgid, messages in enumerate(out_messages):
                self.sim.messagess[pgid].extend(messages)
        return self.sim.messagess[-2]

    def panel(self):
        if not self.sim._db_started:
            self.sim._db_started = True
            self.sim._db.start()
        self.do('panel')

    def aggregate(self):
        if not self.sim._db_started:
            self.sim._db_started = True
            self.sim._db.start()
        self.do('aggregate')


def execute_wrapper(inp):
    # processor_group.execute(self.groups, command, messages[pgid])
    return inp[0].execute(inp[1], inp[2], inp[3])
