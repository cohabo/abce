﻿# Copyright 2012 Davoud Taghawi-Nejad
#
# Module Author: Davoud Taghawi-Nejad
#
# ABCE is open-source software. If you are using ABCE for your research you are
# requested the quote the use of this software.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License and quotation of the
# author. You may obtain a copy of the License at
#       http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations under
# the License.
"""
The :py:class:`abce.Agent` class is the basic class for creating your agents.
It automatically handles the possession of goods of an agent. In order to
produce/transforme goods you also need to subclass the :py:class:`abce.Firm` or
to create a consumer the :py:class:`abce.Household`.

For detailed documentation on:

Trading, see :doc:`Trade`

Logging and data creation, see :doc:`Database`.

Messaging between agents, see :doc:`Messaging`.
"""
from collections import OrderedDict, defaultdict
from .database import Database
from .networklogger import NetworkLogger
from .trade import Trade
from .messaging import Messaging
import time
import random
from abce.expiringgood import ExpiringGood
from pprint import pprint
import traceback
import datetime
from .inventory import Inventory


class DummyContracts:
    def _advance_round(self, round):
        pass


class Agent(Database, NetworkLogger, Trade, Messaging):
    """ Every agent has to inherit this class. It connects the agent to the
    simulation and to other agent. The :class:`abce.Trade`,
    :class:`abce.Database` and :class:`abce.Messaging` classes are included. You
    can enhance an agent, by also inheriting from :class:`abce.Firm`.
    :class:`abce.FirmMultiTechnologies` or :class:`abce.Household`.

    For example::

        class Household(abce.Agent, abce.Household):
            def init(self, simulation_parameters, agent_parameters):
                self.num_firms = simulation_parameters['num_firms']
                self.type = agent_parameters['type']
                ...

            def selling(self):
                for i in range(self.num_firms):
                    self.sell('firm', i, 'good', quantity=1, price=1)

            ...



    """

    def __init__(self, id, group, trade_logging, database, logger, random_seed, num_managers):
        """ Do not overwrite __init__ instead use a method called init instead.
        init is called whenever the agent are build.
        """
        self.id = id
        """ self.id returns the agents id READ ONLY"""
        self.name = (group, id)
        """ self.name returns the agents name, which is the group name and the
        id seperated by '_' e.G. "household_12" READ ONLY!
        """
        self.name_without_colon = '%s_%i' % (group, id)
        self.group = group
        """ self.group returns the agents group or type READ ONLY! """
        # TODO should be group_address(group), but it would not work
        # when fired manual + ':' and manual group_address need to be removed
        self.database_connection = database
        self.logger_connection = logger

        self.trade_logging = {'individual': 1,
                              'group': 2, 'off': 0}[trade_logging]
        self.num_managers = num_managers
        self._out = [[] for _ in range(self.num_managers + 1)]

        self._haves = Inventory(self.name)

        # TODO make defaultdict; delete all key errors regarding self._haves as
        # defaultdict, does not have missing keys
        self._haves['money'] = 0
        self._msgs = {}

        self.given_offers = OrderedDict()
        self._open_offers = defaultdict(dict)
        self._polled_offers = {}
        self._offer_count = 0
        self._reject_offers_retrieved_end_subround = []

        self._trade_log = defaultdict(int)
        self._data_to_observe = {}
        self._data_to_log_1 = {}
        self._quotes = {}
        self.round = None
        """ self.round is depreciated"""
        self.time = None
        """ self.time, contains the time set with simulation.time(time) """
        self._resources = []
        self.variables_to_track_panel = []
        self.variables_to_track_aggregate = []

        random.seed(random_seed)

        try:
            self._add_contracts_list()
        except AttributeError:
            self.contracts = DummyContracts()

    def init(self, parameters, agent_parameters):
        """ This method is called when the agents are build.
        It can be overwritten by the user, to initialize the agents.
        parameters and agent_parameters are the parameters given in
        :py:meth:`abce.Simulation.build_agents`
        """
        pass

    def date(self):
        """ If ABCE is run in calendar mode (via
        :py:meth:`abce.Simulation.declare_calendar`), date shows the current
        date.::

        self.date().day
        self.date().month
        self.date().year
        self.date().weekday()  # the weekday as a number Monday being 0
        self.date().toordinal()  #

        The date works like python's
        `date object
        <https://docs.python.org/2/library/datetime.html#date-objects>`_
        """
        try:
            return datetime.date.fromordinal(self.round)
        except ValueError:
            raise ValueError(
                "you need to run ABCE in calendar mode, use "
                "simulation.declare_calendar(2000, 1, 1)")

    def possession(self, good):
        """ returns how much of good an agent possesses.

        Returns:
            A number.

        possession does not return a dictionary for self.log(...), you can use
        self.possessions([...]) (plural) with self.log.

        Example::

            if self.possession('money') < 1:
                self.financial_crisis = True

            if not(is_positive(self.possession('money')):
                self.bancrupcy = True

        """
        return self._haves.possession(good)

    def possessions(self):
        """ returns all possessions """
        return self._haves.possessions()

    def _offer_counter(self):
        """ returns a unique number for an offer (containing the agent's name)
        """
        self._offer_count += 1
        return hash((self.name, self._offer_count))

    def _advance_round(self, time):
        for offer in list(self.given_offers.values()):
            if offer.made < self.round:
                print("in agent %s this offers have not been retrieved:" %
                      self.name_without_colon)
                for offer in list(self.given_offers.values()):
                    if offer.made < self.round:
                        print(offer.__repr__())
                raise Exception('%s_%i: There are offers have been made before'
                                'last round and not been retrieved in this'
                                'round get_offer(.)' % (self.group, self.id))

        self._haves._advance_round()
        self.contracts._advance_round(self.round)

        if self.trade_logging > 0:
            self.database_connection.put(
                ["trade_log", self._trade_log, self.round])

        self._trade_log = defaultdict(int)

        if sum([len(offers) for offers in list(self._open_offers.values())]):
            pprint(dict(self._open_offers))
            raise Exception('%s_%i: There are offers an agent send that have '
                            'not been retrieved in this round get_offer(.)' %
                            (self.group, self.id))

        if sum([len(offers) for offers in list(self._msgs.values())]):
            pprint(dict(self._msgs))
            raise Exception('%s_%i: There are messages an agent send that have '
                            'not been retrieved in this round get_messages(.)' %
                            (self.group, self.id))

        for ingredient, units, product in self._resources:
            self._haves.create(product, self.possession(ingredient) * units)

        self.round = time
        self.time = time

    def create(self, good, quantity):
        """ creates quantity of the good out of nothing

        Use create with care, as long as you use it only for labor and
        natural resources your model is macro-economically complete.

        Args:
            'good': is the name of the good
            quantity: number
        """
        self._haves.create(good, quantity)

    def create_timestructured(self, good, quantity):
        """ creates quantity of the time structured good out of nothing.
        For example::

            self.creat_timestructured('capital', [10,20,30])

        Creates capital. 10 units are 2 years old 20 units are 1 year old
        and 30 units are new.

        It can alse be used with a quantity instead of an array. In this
        case the amount is equally split on the years.::

            self.create_timestructured('capital', 60)

        In this case 20 units are 2 years old 20 units are 1 year old
        and 20 units are new.

        Args:
            'good':
                is the name of the good

            quantity:
                an arry or number
        """
        self._haves.create_timestructured(good, quantity)

    def _declare_expiring(self, good, duration):
        """ creates a good that has a limited duration
        """
        self._haves[good] = ExpiringGood(duration)
        self._haves._expiring_goods.append(good)

    def destroy(self, good, quantity=None):
        """ destroys quantity of the good. If quantity is omitted destroys all

        Args::

            'good':
                is the name of the good
            quantity (optional):
                number

        Raises::

            NotEnoughGoods: when goods are insufficient
        """
        self._haves.destroy(good, quantity)

    def _set_network_drawing_frequency(self, frequency):
        self._network_drawing_frequency = frequency

    def _execute(self, command, incomming_messages):
        self._out = [[] for _ in range(self.num_managers + 2)]
        try:
            self._clearing__end_of_subround(incomming_messages)
            self._out[-2] = (getattr(self, command)(), )
            self._reject_polled_but_not_accepted_offers()
        except KeyboardInterrupt:
            return None
        except:
            time.sleep(random.random())
            traceback.print_exc()
            raise Exception()

        return self._out

    def _register_resource(self, resource, units, product):
        self._resources.append((resource, units, product))

    def _register_perish(self, good):
        self._haves._perishable.append(good)

    def _register_panel(self, possessions, variables):
        self.possessions_to_track_panel = possessions
        self.variables_to_track_panel = variables

    def _register_aggregate(self, possessions, variables):
        self.possessions_to_track_aggregate = possessions
        self.variables_to_track_aggregate = variables

    def panel(self):
        """ use in action list to create panel data """
        data_to_send = [self.id, self.round]
        for possession in self.possessions_to_track_panel:
            data_to_send.append(self._haves[possession])

        for variable in self.variables_to_track_panel:
            try:
                data_to_send.append(self.__dict__[variable])
            except KeyError:
                data_to_send.append(0.0)
        self.database_connection.put(["panel",
                                      self.group,
                                      data_to_send])

    def aggregate(self):
        """ use in action list to create data """
        data_to_send = [self.round]
        for possession in self.possessions_to_track_aggregate:
            data_to_send.append(self._haves[possession])

        for variable in self.variables_to_track_aggregate:
            try:
                data_to_send.append(self.__dict__[variable])
            except KeyError:
                data_to_send.append(0.0)
        self.database_connection.put(["aggregate",
                                      self.round,
                                      self.group,
                                      data_to_send])

    def _send(self, receiver_group, receiver_id, typ, msg):
        """ sends a message to 'receiver_group', who can be an agent, a group or
        'all'. The agents receives it at the begin of each round in
        self.messages(typ) is 'm' for mails.
        typ =(_o,c,u,r) are
        reserved for internally processed offers.
        """
        self._out[receiver_id % self.num_managers].append(
            (receiver_group, receiver_id, (typ, msg)))

    def create_agent(self, AgentClass, group_name,
                     parameters=None, agent_parameters=None):
        """ create a new agent.

        Args:

            AgentClass:
                the class of agent to create.
                (can be the same class as the creating agent)

            'group_name':
                the name of the group the agent should belong to

            parameters:
                a dictionary of parameters

            agent_parameters:
                a dictionary of parameters

        Example::

            self.create_agent(BeerFirm, 'beerfirm',
                              parameters=self.parameters,
                              agent_parameters={'creation': self.round + 1})
        """
        self._out[-1].append(('add', (AgentClass, group_name,
                                      parameters, agent_parameters)))

    def delete_agent(self, group_name, id, quite=True):
        """ This deletes an agent, an agent can delete itself. There are two
        ways of deleting an agent. By default, quite is set to True, all future
        messages to this agent are deleted. If quite is set to False agents are
        completely deleted. This makes the simulation faster, but if messages
        are send to this agents the simulation stops.

        Args:

            group_name:
                group name of the agent

            id:
                the id of the agent to be deleted

            quite:
                whether the agent deletes incomming messages.
        """
        self._out[-1].append(('delete', (group_name, id, quite)))


def flatten(d, parent_key=''):
    items = []
    for k, v in list(d.items()):
        try:
            items.extend(list(flatten(v, '%s%s_' % (parent_key, k)).items()))
        except AttributeError:
            items.append(('%s%s' % (parent_key, k), v))
    return dict(items)
