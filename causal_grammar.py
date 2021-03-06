"""
causal grammar parser and helper functions
"""
# BACKGLOG: filter out "competing" parse trees below thresh? when is this from?

import itertools
import math # for log, etc
import xml.etree.ElementTree as ET
from xml.dom import minidom
import os
import copy
from collections import defaultdict

"""some helper functions"""
def powerset(iterable):
    "powerset([1,2,3]) --> () (1,) (2,) (3,) (1,2) (1,3) (2,3) (1,2,3)"
    s = list(iterable)
    return itertools.chain.from_iterable(itertools.combinations(s, r) for r in range(len(s)+1))

def flatten(listOfLists):
    "Flatten one level of nesting"
    return itertools.chain.from_iterable(listOfLists)

def split_fluents_into_windows(fluents):
    splits = list()
    kFluentOverlap = 10
    cluster = list()
    prev_frame = -kFluentOverlap
    for frame in sorted(fluents):
        if kFluentOverlap < (frame - prev_frame):
            splits.append(cluster)
            cluster = list()
        prev_frame = frame
        cluster.append(frame)
    splits.append(cluster)
    return splits[1:]

TYPE_FLUENT = "fluent"
TYPE_ACTION = "action"

def floatEqualTo(float1, float2):
	return abs(float1 - float2) < .0000001

kUnknownEnergy = 8.0 #0.7 # TODO: may want to tune
kZeroProbabilityEnergy = 10.0 # TODO: may want to tune: 10.0 = very low
kNonActionPenaltyEnergy = 0. # TODO: need to validate; kind of matches a penalty energy in readActionResults of parsingSummerActionAndFluentOutput

# TODO: REMEMBER THAT THESE CAN BE/ARE OVERRIDDEN BY SUMMERDATA!!!!! TODO
# these are used to keep something that's flipping "around" 50% to not keep triggering fluent changes TODO: no they're not. but they are used in dealWithDbResults for posting "certain" results to the database... and they're passed into the main causal_grammar fn as fluent_on_probability and fluent_off_probability
#kFluentThresholdOnEnergy = 0.36 # TODO: may want to tune: 0.36 = 0.7 probability
#kFluentThresholdOffEnergy = 1.2 # TODO: may want to tune: 1.2 = 0.3 probability

#from summerdata, these are performing well over there....
kFluentThresholdOnEnergy = 0.6892 # 49.7997769
kFluentThresholdOffEnergy = 0.6972 # 50.1977490468

kReportingThresholdEnergy = 0.5 # may want to tune
kDefaultEventTimeout = 10 # shouldn't need to tune because this should be tuned in grammar
kFilterNonEventTriggeredParseTimeouts = False # what the uber-long variable name implies
kDebugEnergies = False # if true, print out fluent current/prev and event energies when completing a parse tree

kFluentStatusUndetected = 1
kFluentStatusOnToOff = 2
kFluentStatusOffToOn = 3
kFluentStatusInsertion = 4

def get_simplified_forest_for_example(forest, example):
	splits = example.split("_")
	fluents = splits[::2]
	if len(splits) % 2:
		fluents = fluents[:-1]
	#pulling in "fluent_extensions" is a hack needed for summerdata, we should figure out how to generalize or remove.... (water/waterstream root nodes specified at the "file name" level also want their "thirst_*" and "cup_*" fluents to be pulled in, don't oversimplify!)
	import summerdata
	more_fluents = []
	for fluent in fluents:
		if fluent in summerdata.fluent_extensions:
			more_fluents = more_fluents + summerdata.fluent_extensions[fluent]
	fluents = set(fluents + more_fluents) #set to make terms distinct just in case
	return get_simplified_forest_for_fluents(forest,fluents)

def get_simplified_forest_for_fluents(forest, fluents):
	#BACKLOG: does not work with phone ~ PHONE_ACTIVE ... fluent = "PHONE_ACTIVE" ... need more universal munging or to make our data uniform throughout
	simplified_forest = []
	for root in forest:
		found = False
		for fluent in fluents:
			if root['symbol'].startswith(fluent + "_"):
				simplified_forest.append(root)
				break
	return simplified_forest

def sequence_generator():
	i = 0
	while 1:
		yield i
		i += 1

actionid_generator = sequence_generator()
fluentid_generator = sequence_generator()
branchid_generator = sequence_generator()

def generate_causal_forest_from_abbreviated_forest(abbreviated_forest):
	forest = []
	for child in abbreviated_forest:
		tree = {}
		if child[0]:
			tree['node_type'] = child[0]
		if child[1]:
			tree['symbol_type'] = child[1]
			if tree['symbol_type'] in ('jump','timer',):
				tree['alternate'] = child[6]
		if child[2]:
			tree['symbol'] = child[2]
		if child[3]:
			tree['probability'] = child[3]
		if child[4]:
			tree['timeout'] = child[4]
		if child[5]:
			tree['children'] = generate_causal_forest_from_abbreviated_forest(child[5])
			
		forest.append(tree)
	return forest

def import_summerdata(exampleName,actionDirectory):
	import parsingSummerActionAndFluentOutput
	fluent_parses = parsingSummerActionAndFluentOutput.readFluentResults(exampleName)
	action_parses = parsingSummerActionAndFluentOutput.readActionResults("{}.{}".format(actionDirectory,exampleName))
	#import pprint
	#pp = pprint.PrettyPrinter(depth=6)
	#pp.pprint(action_parses)
	#pp.pprint(fluent_parses)
	return [fluent_parses, action_parses]

def import_xml(filename):
	fluent_parses = {'initial':{}}
	action_parses = {}
	document = minidom.parse(filename)
	interpretation_chunk = document.getElementsByTagName('interpretation')[0]
	interpretation_probability = float(interpretation_chunk.attributes['probability'].nodeValue)
	interpretation_energy = probability_to_energy(interpretation_probability)
	action_chunk = document.getElementsByTagName('temporal')[0]
	initial_fluents = fluent_parses['initial'];
	for fluent_change in action_chunk.getElementsByTagName('fluent_change'):
		fluent_attributes = fluent_change.attributes;
		frame_number = int(fluent_attributes['frame'].nodeValue)
		fluent = fluent_attributes['fluent'].nodeValue
		if frame_number not in fluent_parses:
			fluent_parses[frame_number] = {}
		frame = fluent_parses[frame_number]
		new_value = fluent_attributes['new_value'].nodeValue
		if new_value == 1 or new_value == '1':
			new_value = interpretation_energy
		elif new_value == 0 or new_value == '0':
			new_value = kZeroProbabilityEnergy
		else:
			raise Exception("new value {} not 1 or 0 for frame {}: {}".format(fluent, frame_number, new_value))
		if fluent not in initial_fluents:
			old_value = fluent_attributes['old_value'].nodeValue
			if old_value == 1 or old_value == '1':
				old_value = interpretation_energy
			elif old_value == 0 or old_value == '0':
				old_value = kZeroProbabilityEnergy
			else:
				raise Exception("old value {} not 1 or 0 for frame {}: {}".format(fluent, frame_number, old_value))
			initial_fluents[fluent] = old_value
		frame[fluent] = new_value
	def add_event(events, agent, frame, name, energy):
		if frame not in events:
			events[frame] = {}
		frame = events[frame]
		frame[name] = {'energy': energy, 'agent': agent}
	for event in action_chunk.getElementsByTagName('event'):
		# all 'action' agents are pulled in as the event agents; actions have one and only one agent
		# events (and actions) are now split into _START and _END
		actions = event.getElementsByTagName('action')
		event_attributes = event.attributes;
		event_start_frame = int(event_attributes['begin_frame'].nodeValue)
		event_end_frame = int(event_attributes['end_frame'].nodeValue)
		event_name = event_attributes['name'].nodeValue
		event_agents = []
		for action in actions:
			action_attributes = action.attributes
			action_start_frame = int(action_attributes['begin_frame'].nodeValue)
			action_end_frame = int(action_attributes['end_frame'].nodeValue)
			action_name = action_attributes['name'].nodeValue
			action_agent = [action_attributes['agent'].nodeValue]
			event_agents.append(action_agent[0])
			add_event(action_parses,action_agent,action_start_frame,"{}_START".format(action_name),interpretation_energy)
			add_event(action_parses,action_agent,action_end_frame,"{}_END".format(action_name),interpretation_energy)
		add_event(action_parses,event_agents,event_start_frame,"{}_START".format(event_name),interpretation_energy)
		add_event(action_parses,event_agents,event_end_frame,"{}_END".format(event_name),interpretation_energy)
	return [fluent_parses,action_parses]

def import_csv(filename, fluents, events):
	raise Exception("THIS IS OUT OF DATE: IT HAS NOT BEEN UPDATED TO HAVE _START AND _END AT THE VERY LEAST")
	fluent_parses = {}
	action_parses = {}
	with open(filename,'r') as file:
		# read the first line as keys
		csv_keys = map(lambda k: k.strip(), file.readline().strip().split(","))
		for fluent in fluents:
			fluents[fluent] = { "to": fluents[fluent], "column": csv_keys.index(fluent) }
		for event in events:
			events[event] = { "to": events[event], "column": csv_keys.index(event) }
		agent = csv_keys.index("Agent")
		for line in file:
			csv_row = map(lambda k: k.strip(), line.strip().split(","))
			frame = int(csv_row[0])
			frame_agent = csv_row[agent]
			for fluent in fluents:
				on_value = float(csv_row[fluents[fluent]['column']])
				if "value" not in fluents[fluent] or fluents[fluent]["value"] != on_value:
					fluents[fluent]["value"] = on_value
					to = fluents[fluent]['to']
					if on_value == 1:
						on_value = 0.0
					elif on_value == 0:
						on_value = kZeroProbabilityEnergy
					else:
						raise Exception("{} not 1 or 0 for frame {}: {}".format(fluent, frame, on_value))
					if frame not in fluent_parses:
						fluent_parses[frame] = {}
					fluent_parses[frame][to] = on_value
			for event in events:
				trigger = float(csv_row[events[event]['column']])
				if trigger == 1:
					to = events[event]['to']
					if frame not in action_parses:
						action_parses[frame] = {}
					action_parses[frame][to] = {"energy": 0.0, "agent": frame_agent}
	return [fluent_parses,action_parses]

def hr():
	print("---------------------------------")

# BACKLOG: a given event is assumed to have the same timeout everywhere in the grammar
def get_event_timeouts(forest):
	events = {}
	for tree in forest:
		if "children" in tree:
			child_timeouts = get_event_timeouts(tree["children"])
			for key in child_timeouts:
				events[key] = int(child_timeouts[key])
		if "symbol_type" in tree:
			if tree["symbol_type"] in ("event","nonevent",):
				if "timeout" in tree:
					events[tree["symbol"]] = int(tree["timeout"])
				else:
					events[tree["symbol"]] = int(kDefaultTimeout)
	return events

def get_fluent_and_event_keys_we_care_about(forest):
	fluents = set()
	events = set()
	for tree in forest:
		if "children" in tree:
			child_keys = get_fluent_and_event_keys_we_care_about(tree["children"])
			fluents.update(child_keys['fluents'])
			events.update(child_keys['events'])
		if "symbol_type" in tree:
			if tree["symbol_type"] in ("fluent","prev_fluent"):
				fluents.add(tree["symbol"])
			elif tree["symbol_type"] in ("event","nonevent"):
				events.add(tree["symbol"])
	return { "fluents": fluents, "events": events }

# filters "changes" for just the fluents and events we care about
# "changes" dict is changed by this function as python is always pass-by-reference
def filter_changes(changes, keys_in_grammar):
	keys_for_filtering = []
	for key in keys_in_grammar:
		# print("testing: {}".format(key))
		if "_" in key:
			prefix, postfix = key.rsplit("_",1)
			if postfix in ("on","off"):
				keys_for_filtering.append(prefix)
				continue
		keys_for_filtering.append(key)
	keys_for_filtering = set(keys_for_filtering)
	# print("KEYS FOR FILTERING: {}".format(keys_for_filtering))
	for x in [x for x in changes.keys() if x not in keys_for_filtering]:
		changes.pop(x)

# returns a forest where each option is a different parse. the parses have the same format as trees (but or-nodes now only have one option selected).
def generate_parses(causal_tree):
	node_type = causal_tree["node_type"]
	if "children" not in causal_tree:
		return (causal_tree,)
	partial_causal_parses = []
	# make a copy of the current node, minus the children (so we're keeping symbol_type, symbol, energy, node_type, etc)
	current_node = causal_tree.copy()
	current_node.pop("children")
	if node_type in ("or","root",):
		for child_node in causal_tree["children"]:
			for parse in generate_parses(child_node):
				current_node["children"] = (parse,)
				partial_causal_parses.append(current_node.copy())
	elif node_type in ("and",):
		# generate causal parses on each tree
		# build all cartesian products of those causal parses;
		# each cartesian product is a set of children for the and node, a separate partial parse graph to return
		child_parses = []
		for child_node in causal_tree["children"]:
			child_parses.append(generate_parses(child_node),)
		for product in itertools.product(*child_parses):
			current_node["children"] = product
			partial_causal_parses.append(current_node.copy())
	else:
		raise Exception("UNKNOWN NODE TYPE: {}".format(node_type))
	return partial_causal_parses

def energy_to_probability(energy):
	return math.exp(-energy)

def opposite_energy(energy):
	p = energy_to_probability(energy)
	return probability_to_energy(1.-p)

def probability_to_energy(probability):
	if not type(probability) is int and not type(probability) is float:
		# what we've got here is a lambda, and if we're asking this, we're asking wrong
		raise Exception("NO, wait... '{}'".format(probability))
		return kZeroProbabilityEnergy
	if floatEqualTo(0.,probability):
		return kZeroProbabilityEnergy
	else:
		return -math.log(probability)

# changes '.*_on' to '.*_off' and vice versa
def invert_name(fluent):
	parts = fluent.split('_')
	if parts[-1] in ('on','off'):
		completion = {'on': 'off', 'off': 'on'}
	else:
		raise Exception("Unable to invert fluent '{}'".format(fluent))
	# which is more perverse? :)
	#return "{}_{}".format('_'.join(parts[:-1]),completion[parts[-1]])
	return '_'.join(parts[:-1] + [completion[parts[-1]],])

def has_prev_symbol(node, symbol):
	node_type = node.get('node_type',False)
	node_symbol_type = node.get('symbol_type',False)
	node_symbol = node.get('symbol',False)
	if node_symbol_type == 'prev_fluent' and node_symbol == symbol:
		return True
	if 'children' in node:
		for child in node['children']:
			if has_prev_symbol(child, symbol):
				return True
	return False

# get lowest "energy" out of list of dicts {'energy':,'frame':}
def get_best_energy_event(events, used=set(), newerthan=0):
	filtered = [event for event in events if event['frame'] not in used and event['frame'] > newerthan]
	foo = sorted(filtered, key = lambda(k): k['energy'])
	if len(foo) == 0:
		retval = {'energy': kZeroProbabilityEnergy, 'frame': -1, 'agent': None }
	else:
		retval = foo[0]
	#print("Getting best energy from {} excepting {}\n->{} Newerthan {}".format(events, used, retval, newerthan))
	#print("\tFiltered: {}".format(filtered))
	#print("\tSorted: {}".format(foo))
	return retval

debug_calculate_energy = False
def calculate_energy(node, energies, actions_used = None, is_flip = False, frame=-1, event_timeouts=dict()):
	fluent_energies = energies[0]
	event_energies = energies[1]
	root = False
	node_type = node.get('node_type',False)
	symbol_type = node.get('symbol_type',False)
	if node_type == 'root':
		root = True
		if actions_used == None:
			actions_used = node['actions_used'] if 'actions_used' in node else None
		# now we're going to see if we are a "flip" node, because in flip nodes we wholeheartedely trust our detectors...
		# so we're going to replace the value "unknown energy" with "zero energy" (not to be confused with zero point energy)
		if symbol_type == 'fluent' and has_prev_symbol(node, invert_name(node['symbol'])):
			if node['symbol'].endswith("_on"):
				is_flip = kFluentStatusOffToOn
			else:
				is_flip = kFluentStatusOnToOff
		else:
			is_flip = kFluentStatusUndetected
			flip_string = "n/a"
	if kFluentStatusUndetected == is_flip:
		flip_string = "n/a"
	elif kFluentStatusOffToOn == is_flip:
		flip_string = "off->on"
	elif kFluentStatusOnToOff == is_flip:
		flip_string = "on->off"
	else:
		flip_string = "??"
	global debug_calculate_energy
	if debug_calculate_energy:
		if root:
			print("-------- ROOT [flip: {}]------".format(flip_string))
		print("NODE: {}".format(node))
	node_energy = 0.0
	if "probability" in node:
		# coming off a "root" or "or" node_type
		tmp_energy = probability_to_energy(node["probability"])
		node_energy += tmp_energy
		if debug_calculate_energy:
			print("+ {:4.4} from probability".format(tmp_energy))
	if symbol_type:
		symbol = node['symbol']
		if symbol_type in ("fluent","prev_fluent",):
			status = fluent_energies[symbol]['status']
			if status == kFluentStatusInsertion:
				if is_flip == kFluentStatusUndetected:
					tmp_energy = kUnknownEnergy
				else:
					tmp_energy = kZeroProbabilityEnergy
			elif status == kFluentStatusUndetected:
				if is_flip == kFluentStatusUndetected:
					tmp_energy = kUnknownEnergy
				else:
					tmp_energy = kZeroProbabilityEnergy
			else:
				if is_flip == kFluentStatusUndetected:
					tmp_energy = kUnknownEnergy
				else:
					if is_flip != status:
						tmp_energy = kZeroProbabilityEnergy
					else:
						if symbol_type in ("prev_fluent",):
							opposite_symbol = invert_name(symbol)
							tmp_energy = fluent_energies[opposite_symbol]['energy']
						else:
							tmp_energy = fluent_energies[symbol]['energy']
			node_energy += tmp_energy
			if debug_calculate_energy:
				prev = "prev_" if symbol_type in ("prev_fluent",) else "";
				print("+ {:4.4} from {}fluent {} [flip {}; status {}]".format(tmp_energy,prev,symbol,flip_string,status))
		elif symbol_type in ("event",):
			frames_used = actions_used[symbol] if actions_used and symbol in actions_used else set()
			newerthan=(frame - event_timeouts[symbol])
			tmp_energy_event = get_best_energy_event(event_energies[symbol], frames_used, newerthan = newerthan)
			tmp_energy = tmp_energy_event['energy']
			if debug_calculate_energy:
				# throwing in float converters because int-like zeros got in?
				print("+ {:4.4} from event {} [{}]".format(float(tmp_energy),symbol,tmp_energy_event))
			node_energy += tmp_energy
		elif symbol_type in ("nonevent",):
			frames_used = actions_used[symbol] if actions_used and symbol in actions_used else set()
			if not symbol in event_timeouts:
				raise Exception("{} not found in {}".format(symbol,event_timeouts))
			newerthan=(frame - event_timeouts[symbol])
			tmp_energy_event = get_best_energy_event(event_energies[symbol], frames_used, newerthan=newerthan)
			tmp_energy = opposite_energy(tmp_energy_event['energy'])
			if debug_calculate_energy:
				print("+ {:4.4} from nonevent {} [{}]".format(float(tmp_energy),symbol,tmp_energy_event))
				print("+ {:4.4} from kNonActionPenalty".format(kNonActionPenaltyEnergy))
			node_energy += tmp_energy + kNonActionPenaltyEnergy
		elif symbol_type in ("timer","jump",):
			# these are zero-probability events at this stage of evaluation
			#tmp_energy = event_energies[symbol]["energy"]
			#node_energy += probability_to_energy(1-energy_to_probability(tmp_energy))
			pass # BACKLOG: should this be dealt with in some other way?
		else:
			raise Exception("unhandled symbol_type '{}'".format(symbol_type))
	if "children" in node:
		# "multiplies" child probabilities on all nodes (note to self: root nodes are always or nodes)
		# averaging on "and" nodes...need to work through that better
		# for now, it makes little difference as trees are neither deep nor wide
		average_ands = True
		if not average_ands or node_type in ("or","root",):
			# "multiplies" child probabilities on "or" nodes (root nodes are always or nodes)
			for child in node["children"]:
				child_energy = calculate_energy(child, energies, actions_used, is_flip,frame,event_timeouts)
				node_energy += child_energy
		else:
			# "averages" over the "and" nodes
			child_energy = 0
			for child in node["children"]:
				child_energy += calculate_energy(child, energies, actions_used, is_flip,frame,event_timeouts)
			node_energy += 2. * (child_energy / len(node["children"])) # scale back to 2 nodes
	if debug_calculate_energy:
		print("TOTAL: {:4.4}".format(node_energy))
	return node_energy

# this makes some very naiive assumptions about jumping--that the "paired" fluent(s) will all be met, and (others?)
def parse_can_jump_from(parse,prev_parse):
	# "timer" -> "jump"
	timer = get_symbol_matches_from_parse("timer",prev_parse)
	jump = get_symbol_matches_from_parse("jump",prev_parse)
	if timer and jump and timer["alternate"] == parse["symbol"] and timer["symbol"] == jump["symbol"]:
		return True
	return False

def get_symbol_matches_from_parse(symbol,parse):
	matches = []
	if "symbol_type" in parse:
		if parse["symbol_type"] == symbol:
			matches.append(parse)
	if "children" in parse:
		for child in parse["children"]:
			child_matches = get_symbol_matches_from_parse(symbol,child)
			matches += child_matches
	return matches

def parse_is_consistent_with_requirement(parse,requirement):
	if 'symbol_type' in parse:
		antithesis = invert_name(requirement)
		if parse['symbol_type'] in ('prev_fluent',) and parse['symbol'] == antithesis:
			return False
	if "children" in parse:
		for child in parse['children']:
			if not parse_is_consistent_with_requirement(child,requirement):
				return False
	return True

def make_tree_like_lisp(causal_tree):
	my_symbol = "?"
	if "symbol" in causal_tree:
		my_symbol = causal_tree["symbol"]
	if "children" not in causal_tree:
		if "symbol_type" in causal_tree and causal_tree["symbol_type"] in ("nonevent",):
			return "".join(("NOT ",my_symbol))
		elif "symbol_type" in causal_tree and causal_tree["symbol_type"] in ("prev_fluent",):
			return "".join(("PREV ",my_symbol))
		else:
			return my_symbol
	simple_children = []
	for child in causal_tree["children"]:
		simple_children.append(make_tree_like_lisp(child))
	return (my_symbol, simple_children)

def get_energies_used(actions_used, energies, prev_used = dict()):
	events_used = dict()
	#print("PREV USED: {}".format(prev_used))
	for action in actions_used:
		#print("CHECKING {}".format(energies))
		energy = get_best_energy_event(energies[action], prev_used[action] if action in prev_used else set())
		frame = energy['frame']
		if frame >= 0:
			events_used[action] = set([frame])
	#print("NOW USED: {}".format(events_used))
	return events_used

def get_actions_used(parse, first = True):
	actions = set()
	if "symbol_type" in parse and parse["symbol_type"] in ("event",):
		actions.add(parse['symbol'])
		#print("EVENT USED: {}".format(causal_tree['symbol']))
	if "children" in parse:
		for child in parse['children']:
			actions.update(get_actions_used(child, False))
	return actions

def merge_actions_used(actions1, actions2):
	# actions are just key->framelist
	retval = dict()
	for key in actions1:
		retval[key] = actions1[key].copy()
	for key in actions2:
		if not key in retval:
			retval[key] = set()
		retval[key].update(actions2[key].copy())
	#print("MERGING {} + {} -> {}".format(actions1,actions2,retval))
	return retval

def get_energies(fluent_hash,event_hash):
	fluent_energies = {}
	for fluent in fluent_hash:
		fluent_energies[fluent] = {"energy":fluent_hash[fluent]["energy"],"status":fluent_hash[fluent]["status"]}
	event_energies = {}
	event_frames = {}
	for event in event_hash:
		# energies is [event] -> [energy: {}, frame: {}]
		event_energies[event] = event_hash[event]['energies'][:]
	return (fluent_energies, event_energies)

def debug_energies(fluent_hash,event_hash):
	print_energies(fluent_hash,event_hash)
	print_previous_energies(fluent_hash)
	hr()

def print_energies(fluent_hash,event_hash):
	#fluent_energies = dict((k,k[v]) for k,v in fluent_hash.items() if v == "energy")
	fluent_energies, event_energies = get_energies(fluent_hash, event_hash)
	print("CURRENT FLUENT: {}".format(fluent_energies))
	print("CURRENT EVENT: {}".format(event_energies))

def wipe_fluent_hash(fluent_hash):
	for fluent in fluent_hash:
		fluent_hash[fluent]['energy'] = kUnknownEnergy
		fluent_hash[fluent]['status'] = kFluentStatusUndetected

# removes any events that haven't triggered within their timeout number of frames
def clear_outdated_events(event_hash, event_timeouts, frame):
	for event in event_hash:
		energies = [x for x in event_hash[event]['energies'] if (frame - x['frame']) > event_timeouts[event]]

# at all times there is a list of "currently active" parses, which includes a chain back to the beginning
# of events of the "best choice of transition" from each event (action, fluent, or timeout) to each previous
def complete_parse_tree(active_parse_tree, fluent_hash, event_hash, frame, completions, source, event_timeouts):
	# we have a winner! let's show them what they've won, bob!
	global debug_calculate_energy
	#debug_calculate_energy = True
	### don't need this energy = calculate_energy(active_parse_tree, get_energies(fluent_hash, event_hash))
	debug_calculate_energy = False
	fluent = active_parse_tree["symbol"]
	agents_responsible = []
	# if there are agents in the parse, print out who they were
	keys = get_fluent_and_event_keys_we_care_about((active_parse_tree,))
	# WARNING: if we have two event types in the same parse, we can wind up adding the same parse multiple times.
	# BACKLOG: make sure the "if not found" solution below doesn't break anything else when it solves the above
	for event_key in keys["events"]:
		event = get_best_energy_event(event_hash[event_key]['energies'],newerthan=(frame - event_timeouts[event_key]))
		agent = event["agent"]
		if agent:
			agents_responsible.append(agent,)
		if "_" in fluent:
			prefix, postfix = fluent.rsplit("_",1)
			if postfix in ("on","off",):
				fluent = prefix
		if fluent not in completions:
			completions[fluent] = {}
		completion = completions[fluent]
		if frame not in completion:
			completion[frame] = []
		completion_frame = completion[frame]
		found = False
		for item in completion_frame:
			if item['parse']['id'] == active_parse_tree['id']:
				found = True
				break
		if not found:
			#completion_frame.append({"frame": frame, "fluent": fluent, "energy": energy, "parse": active_parse_tree, "agents": agents_responsible, "sum": fluent_hash[active_parse_tree['symbol']]['energy'], 'source': source})
			completion_frame.append({"frame": frame, "fluent": fluent, "parse": active_parse_tree, "agents": agents_responsible, "sum": fluent_hash[active_parse_tree['symbol']]['energy'], 'source': source})
	#print("{}".format("\t".join([str(fluent),str(frame),"{:g}".format(energy),str(make_tree_like_lisp(active_parse_tree)),str(agents_responsible)])))
	#print("{} PARSE TREE {} COMPLETED at {}: energy({}) BY {}\n{}\n***{}***".format(fluent,active_parse_tree['id'],frame,energy,source,make_tree_like_lisp(active_parse_tree),active_parse_tree))
	#print("Agents responsible: {}".format(agents_responsible))
	if kDebugEnergies:
		debug_energies(fluent_hash, event_hash)

def add_missing_parses(fluent, fluent_hash, event_hash, frame, completions):
	## here we're just getting the completions for one specific frame
	## we want to go through all the possible parses for that fluent
	## and make sure they're spoken for in completions
	#print "ADDING MISSING PARSES"
	for symbol in (completions[0]['parse']['symbol'],):
		parse_ids_completed = []
		for completion in completions:
			parse_ids_completed.append(completion['parse']['id'])
		#print("IDS: {}".format(parse_ids_completed))
		anti_symbol = invert_name(symbol)
		possible_trees = fluent_hash[symbol]['trees']
		unpossible_trees = fluent_hash[anti_symbol]['trees']
		for possible_tree in possible_trees + unpossible_trees:
			# if this tree is a "primary" for this symbol
			if possible_tree['symbol'] in (symbol,anti_symbol):
				other_parses = possible_tree['parses']
				for other_parse in other_parses:
					if other_parse['id'] not in parse_ids_completed:
						parse_ids_completed.append(other_parse['id'])
						#print("ADDING ID: {}".format(other_parse['id']))
						#complete_parse_tree(other_parse, fluent_hash, event_hash, effective_frames[symbol], completions, 'missing') ### what is this 'effective frames' thing?
						#complete_parse_tree(other_parse, fluent_hash, event_hash, frame, completions, 'missing')
						# we have a winner! let's show them what they've won, bob!
						#### don't need this energy = calculate_energy(other_parse, get_energies(fluent_hash, event_hash))
						agents_responsible = []
						source = 'missing'
						#completions.append({"frame": frame, "fluent": fluent, "energy": energy, "parse": other_parse, "agents": agents_responsible, "sum": fluent_hash[other_parse['symbol']]['energy'], 'source': source})
						completions.append({"frame": frame, "fluent": fluent, "parse": other_parse, "agents": agents_responsible, "sum": fluent_hash[other_parse['symbol']]['energy'], 'source': source})
						#print("{}".format("\t".join([str(fluent),str(frame),"{:g}".format(energy),str(make_tree_like_lisp(other_parse)),str(agents_responsible)])))
						#print("{} PARSE TREE {} COMPLETED at {}: energy({}) BY {}\n{}\n***{}***".format(fluent,other_parse['id'],frame,energy,source,make_tree_like_lisp(other_parse),other_parse))
						#print("Agents responsible: {}".format(agents_responsible))
						if kDebugEnergies:
							debug_energies(fluent_hash, event_hash)
	#print "---"
	return completions

# clears out any parses that have not been touched within N frames, printing out any over reporting_threshold_energy
def complete_outdated_parses(active_parses, parse_array, fluent_hash, event_hash, event_timeouts, frame, reporting_threshold_energy, completions):
	# we're planning to remove things from active_parses while we loop through, so....
	active_parses_copy = active_parses.copy()
	parse_ids_completed = []
	parse_symbols_completed = []
	effective_frames = {}
	for parse_id in active_parses_copy:
		active_parse = parse_array[parse_id]
		symbol = active_parse['symbol']
		# get max event timeout relevant to given active_parse
		keys = get_fluent_and_event_keys_we_care_about((active_parse,))
		events = keys["events"]
		max_event_timeout = 0
		for event in events:
			event_timeout = event_timeouts[event]
			if event_timeout > max_event_timeout:
				max_event_timeout = event_timeout
		# if parse was last updated longer ago than max event timeout frames, cull
		if frame - active_parse['frame'] > max_event_timeout:
			# print("REMOVING {}".format(parse_id))
			active_parses.pop(parse_id)
			effective_frame = active_parse['frame'] # + max_event_timeout
			parse_ids_completed.append(parse_id,)
			parse_symbols_completed.append(symbol,)
			effective_frames[symbol] = effective_frame
			complete_parse_tree(active_parse, fluent_hash, event_hash, effective_frame, completions, 'timeout', event_timeouts)
	for symbol in parse_symbols_completed:
		anti_symbol = invert_name(symbol)
		possible_trees = fluent_hash[symbol]['trees']
		unpossible_trees = fluent_hash[anti_symbol]['trees']
		for possible_tree in possible_trees: # + unpossible_trees:
			# if this tree is a "primary" for this symbol
			if possible_tree['symbol'] in (symbol,anti_symbol):
				other_parses = possible_tree['parses']
				for other_parse in other_parses:
					if other_parse['id'] not in parse_ids_completed:
						# BACKLOG: dealing with a bug somewhere that's adding duplicate
						# copies of (some?) parses into fluent_hash[symbol][trees][parses]
						# maybe the trees themselves are referenced multiple times and so
						# added to? anyway, we can work around that by not doing the same
						# id multiple times here
						# raise Exception("ERROR 0x5410269 - EH??")
						parse_ids_completed.append(other_parse['id'])
						complete_parse_tree(other_parse, fluent_hash, event_hash, effective_frames[symbol], completions, 'timeout alt', event_timeouts)
	clear_outdated_events(event_hash, event_timeouts, frame)

def process_events_and_fluents(causal_forest, fluent_parses, action_parses, fluent_threshold_on_energy, fluent_threshold_off_energy, reporting_threshold_energy, suppress_output = False, handle_overlapping_events = False, insert_empty_fluents=True, require_consistency=True):
	clever = True # clever (modified viterbi algorithm) or brute force (all possible parses)
	initial_conditions = False
	#BACKLOG: investigate where initial conditions are coming from, and terminate them....
	if "initial" in fluent_parses:
		initial_conditions = fluent_parses["initial"]
		del fluent_parses["initial"]
		raise Exception("we want to remove this")
	# do these for our local function, because we want these for figuring out which ones overlap
	fluent_parse_frames = sorted(fluent_parses, key=fluent_parses.get)
	fluent_parse_frames.sort()
	action_parse_frames = sorted(action_parses, key=action_parses.get)
	action_parse_frames.sort()
	fluent_and_event_keys_we_care_about = get_fluent_and_event_keys_we_care_about(causal_forest)
	if insert_empty_fluents:
		if len(fluent_parse_frames) > 0:
			empty_fluent = fluent_parses[fluent_parse_frames[0]]
			empty_fluent = empty_fluent.keys()[0]
			empty_fluent = { empty_fluent: -1 }
		elif len(action_parse_frames) > 0:
			#empty_action = action_parses[action_parse_frames[0]].keys()[0]
			empty_fluent = { "TBD": -1 }
		else:
			#print("action_parses: {}".format(action_parses))
			# print("keys: {}".format(fluent_and_event_keys_we_care_about))
			raise Exception("NEED ANOTHER WAY TO GET A RELEVANT 'empty' FLUENT HERE")
		all_frames = sorted(action_parse_frames + fluent_parse_frames)
		new_fluents = dict()
		for x,y in [x for x in itertools.izip(all_frames[:-1],all_frames[1:]) if (x[1] - x[0]) > 1]:
			inserted_frame = int((y + x)/2)
			fluent_parses[inserted_frame ] = empty_fluent
		fluent_parse_frames = sorted(fluent_parses, key=fluent_parses.get)
		fluent_parse_frames.sort()
	if not suppress_output:
		print("CAUSAL FOREST INPUT: {}".format(causal_forest))
	print("FLUENT PARSES: {}".format(fluent_parses))
	# kind of a hack to attach fluent and event keys to each causal tree, lots of maps to make looking things up quick and easy
	# ALSO used to track current energies, which is confusing and broken
	event_hash = {}
	fluent_hash = {}
	event_timeouts = get_event_timeouts(causal_forest)
	# build out the list of all event types in our forest, setting their initial (frame -1) values
	# to kZeroProbabilityEnergy, and making a lookup to all relevant causal trees for those event types;
	# also build out the list of all fluent types in our forest, setting their initial
	# energy to unknown/undetected
	for causal_tree in causal_forest:
		keys = get_fluent_and_event_keys_we_care_about([causal_tree])
		for key in keys['events']:
			if not key in event_hash:
				# initialize our event_hash for that key if we haven't seen it in another tree
				event_hash[key] = {"energies": list(), "trees": [causal_tree,]}
			else:
				event_hash[key]["trees"].append(causal_tree)
		for key in keys['fluents']:
			if key in fluent_hash:
				fluent_hash[key]["trees"].append(causal_tree)
			else:
				# new fluent goes into our hash, set it up with initial conditions if we have those
				fluent_hash[key] = {"energy": kUnknownEnergy, "trees": [causal_tree,], 'status': kFluentStatusUndetected, }

	# build lookups by fluent and event -- the parse_array will be all of the parses,
	# while the parse_id_hash* will list, for each fluent and event respectively, all of the
	# parses associated with it; these parses are flattened per generate_parses (they are implicitly
	# selected on OR nodes, so they depend only on one set of all things being true)
	parse_array = []
	parse_id_hash_by_fluent = {}
	parse_id_hash_by_event = {}
	parseid_generator = sequence_generator()
	for causal_tree in causal_forest:
		causal_tree["parses"] = generate_parses(causal_tree)
		for parse in causal_tree["parses"]:
			parse_id = parseid_generator.next()
			parse["id"] = parse_id
			parse_array.append(parse)
			keys = get_fluent_and_event_keys_we_care_about((parse,))
			for key in keys['events']:
				if key in parse_id_hash_by_event:
					parse_id_hash_by_event[key].append(parse_id)
				else:
					parse_id_hash_by_event[key] = [parse_id,]
			for key in keys['fluents']:
				if key in parse_id_hash_by_fluent:
					parse_id_hash_by_fluent[key].append(parse_id)
				else:
					parse_id_hash_by_fluent[key] = [parse_id,]
			#print("*: {}".format(parse))
			#parse_energy = calculate_energy(parse, get_energies(fluent_hash, event_hash))
			#print("E: {}".format(parse_energy))
	# loop through the parses, getting the "next frame a change happens in"; if a change happens
	# in both at the same time, they will be handled sequentially, the fluent first
	completions = {}
	import pprint
	pp = pprint.PrettyPrinter(depth=6)
	# "complete" the initial parses, which is to say "make the energies for all of our initial state possibilities"
	for parse in parse_array:
		complete_parse_tree(parse, fluent_hash, event_hash, 0, completions, 'initial', event_timeouts)
	if not suppress_output:
		print("PARSE_ARRAY")
		#pp.pprint(parse_array)
		for parse in parse_array:
			print("{}: {}".format(parse['id'],str(make_tree_like_lisp(parse))))
		hr()
		print("COMPLETIONS AFTER INITIAL")
		for symbol_key, frames in completions.items():
			for frame, completion in frames.items():
				print("{} [frame {}]".format(symbol_key, frame))
				for parse in completion:
					# this shouldn't be necessary, but it /seems/ to be necessary at the moment to keep it from crashing....
					parse['energy'] = calculate_energy(parse['parse'], get_energies(fluent_hash, event_hash),frame=frame,event_timeouts=event_timeouts)
					print("\t{} [id {}]".format(parse['energy'],parse['parse']['id']))
		hr()
		#pp.pprint("----")
		#print("FLUENT_HASH")
		#pp.pprint(fluent_hash)
		#print("EVENT_HASH")
		#pp.pprint(event_hash)
		#pp.pprint("----")

	# loop through the parses, getting the "next frame a change happens in"; if a change happens
	# in both fluents and events at the same time, they will be handled sequentially,
	# the fluent first
	# BACKLOG: create every combination that removes overlapping fluents and overlapping actions....

	#print "-=-=-=-=-=-=-= fluent parses -=-=-=-=-=-=-="
	#print fluent_parses
	# {8: {'light': 0.10536051565782628}, 6: {'light': 0.5108256237659907}}
	#print "-=-=-=-=-=-=-= event parses -=-=-=-=-=-=-="
	#print action_parses
	# {5: {'A1': {'energy': 0.10536051565782628, 'agent': 'uuid4'}}}
	#print "-=-=-=-=-=-=-= ...........  -=-=-=-=-=-=-="

	if not suppress_output:
		print "FLUENT AND EVENT KEYS WE CARE ABOUT: {}".format(fluent_and_event_keys_we_care_about)
	# ONLY MIXING UP FLUENT PARSES AS A STARTER. ACITON PARSES WOULD MEAN MORE INTERACTIONS, MORE COMPLEXITY
	# SEE inference-overlappingevents jupyter file to make sense of below
	results_for_xml_output = list()
	if handle_overlapping_events:
		fluents_to_recombine = defaultdict(set)
		for frame in fluent_parses:
			for fluent in fluent_parses[frame]:
				fluents_to_recombine[fluent].add(frame)
		powersets = dict()
		for fluent in fluents_to_recombine:
			frames_to_recombine = fluents_to_recombine[fluent]
			splits = split_fluents_into_windows(frames_to_recombine)
			if not suppress_output:
				print("GOT SPLITS {} for {}".format(splits, fluent))
			split_combinations = list()
			for item in splits:
				split_combinations.append(list(powerset(item))[1:])
			all_combos = split_combinations[0]
			for i in range(1,len(split_combinations)):
				all_combos = list(list(flatten(x)) for x in itertools.product(all_combos, split_combinations[i]))
			powersets[fluent] = all_combos
		powerset_counts = map(lambda x: (x,len(powersets[x]),),powersets.keys())
		powerset_count_split_combinations = map(lambda x: range(0,x[1]),powerset_counts)
		if not suppress_output:
			print("powersets: {}".format(powersets))
			print("powerset counts: {}".format(powerset_counts))
			print("combinations: {}".format(powerset_count_split_combinations))
		if len(powerset_count_split_combinations) > 1:
			merge_combinations = list(itertools.product(powerset_count_split_combinations[0], powerset_count_split_combinations[1]))
			for item in powerset_count_split_combinations[2:]:
				merge_combinations = list(itertools.product(merge_combinations, item))
				merge_combinations = list(list(flatten(x)) for x in map(lambda x: (x[0],(x[1],)),merge_combinations))
		elif not powerset_count_split_combinations:
			merge_combinations = list()
		else:
			merge_combinations = powerset_count_split_combinations[0]
		if not suppress_output:
			print("MERGE_COMBINATIONS: {}".format(merge_combinations))
		for combination in merge_combinations:
			if not suppress_output:
				print("RUNNING COMBINATION: {}".format(combination))
			if type(combination) == type(1):
				combination = (combination, )
			parses_to_recombine = dict(map(lambda x:(x[0][0],powersets[x[0][0]][x[1]]),zip(powerset_counts,combination)))
			recombined_parses = defaultdict(dict)
			#print parses_to_recombine ~ {'door': [175, 191, 272], 'light': (227,), 'screen': [147, 175]}
			if not suppress_output:
				print("parses to recombine: {}".format(parses_to_recombine))
			for fluent in parses_to_recombine:
				for frame in parses_to_recombine[fluent]:
					recombined_parses[frame][fluent] = fluent_parses[frame][fluent]
			result = _without_overlaps(recombined_parses, action_parses, parse_array, copy.deepcopy(event_hash), copy.deepcopy(fluent_hash), event_timeouts, reporting_threshold_energy, copy.deepcopy(completions), fluent_and_event_keys_we_care_about, parse_id_hash_by_fluent, parse_id_hash_by_event, fluent_threshold_on_energy, fluent_threshold_off_energy, suppress_output, clever, require_consistency)
			results_for_xml_output.append(copy.deepcopy(result))
	if not handle_overlapping_events or not merge_combinations:
		result = _without_overlaps(fluent_parses, action_parses, parse_array, copy.deepcopy(event_hash), copy.deepcopy(fluent_hash), event_timeouts, reporting_threshold_energy, copy.deepcopy(completions), fluent_and_event_keys_we_care_about, parse_id_hash_by_fluent, parse_id_hash_by_event, fluent_threshold_on_energy, fluent_threshold_off_energy, suppress_output, clever, require_consistency)
		results_for_xml_output.append(copy.deepcopy(result))
	try:
		#TODO
		#winner-takes-all per overlaps based on the sorting of the first fluent's score...
		#doesn't entirely make sense in retrospect
		if len(results_for_xml_output[0]) > 0:
				results_for_xml_output = sorted(results_for_xml_output, key = lambda(k): k[0][0][2])
		# this should be the better answer, sorting each fluent chain instead of winner-takes all....
		"""
		columns = len(results_for_xml_output[0])
		for column in range(0,columns):
			column_sorted = sorted([result[column] for result in results_for_xml_output], key = lambda(k): (k[0][2]))
			for row in range(0,len(column_sorted)):
				results_for_xml_output[row][column] = column_sorted[row]
		"""
	except IndexError as ie:
		print("INDEX OUT OF RANGE AGAINST {}".format(results_for_xml_output))
		raise ie
	doc = build_xml_output_for_chain(results_for_xml_output[0],parse_array,suppress_output) # for lowest energy chain
	bests = list()
	if not suppress_output:
		print("BEST RESULT ::")
		import pprint as pp
		pp.pprint(results_for_xml_output[0])
		print("BEST RESULT as XML::")
		print("{}".format(minidom.parseString(ET.tostring(doc,method='xml',encoding='utf-8')).toprettyxml(encoding="utf-8",indent="\t")))
		print "----------------------------------------------------"
	return ET.tostring(doc,encoding="utf-8",method="xml")

def _without_overlaps(fluent_parses, action_parses, parse_array, event_hash, fluent_hash, event_timeouts, reporting_threshold_energy, completions, fluent_and_event_keys_we_care_about, parse_id_hash_by_fluent, parse_id_hash_by_event, fluent_threshold_on_energy, fluent_threshold_off_energy, suppress_output, clever, require_consistency):
	results_for_xml_output = []
	active_parse_trees = {}
	fluent_parse_frames = sorted(fluent_parses)
	action_parse_frames = sorted(action_parses)

	fluent_parse_index = 0
	action_parse_index = 0
	super_debug_energies = False
	#super_debug_energies = True
	frame = -1
	# UnboundLocalErorr: local variable 'frame' referenced before assignment in complete_outdated_parses call below.
	# BACKLOG
	# this should not happen because we only come in here when we have frames. What does that mean!?
	# since we complete 'actions' when we look at fluents, if they happen in the same frame, we should probably be handling actions first
	events_and_fluents_at_frame = {} # track energies of events and fluents at every frame, because we're losing it...
	events_and_fluents_at_frame[0] = get_energies(fluent_hash, event_hash)
	while fluent_parse_index < len(fluent_parses) or action_parse_index < len(action_parses):
		fluents_complete = fluent_parse_index >= len(fluent_parses)
		action_complete = action_parse_index >= len(action_parses)
		# if we're not done with our fluents and either we're done with our actions OR next fluent frame is <= next action frame
		if not fluents_complete and (action_complete or fluent_parse_frames[fluent_parse_index] <= action_parse_frames[action_parse_index]):
			frame = fluent_parse_frames[fluent_parse_index]
			# print("CHECKING FLUENT FRAME: {}".format(frame))
			# before we do anything with our new fluent information, complete any actions-that-need-timing out!
			complete_outdated_parses(active_parse_trees, parse_array, fluent_hash, event_hash, event_timeouts, frame, reporting_threshold_energy, completions)
			changes = fluent_parses[frame]
			filter_changes(changes, fluent_and_event_keys_we_care_about['fluents'])
			fluent_parse_index += 1
			# reset all our existing fluents to kUnknownEnergy, because it's a new frame and we're
			# going to try NOT tracking anything
			wipe_fluent_hash(fluent_hash)
			for fluent in changes:
				fluent_on_energy = changes[fluent]
				fluent_on_name = "{}_on".format(fluent)
				fluent_off_name = "{}_off".format(fluent)
				if fluent_on_energy < 0:
					# this is a special fluent, "insertion", not an actual detection... handled special in calculate_energy
					fluent_hash[fluent_on_name]["energy"] = fluent_on_energy
					fluent_hash[fluent_on_name]["status"] = kFluentStatusInsertion
					fluent_hash[fluent_off_name]["energy"] = fluent_on_energy
					fluent_hash[fluent_off_name]["status"] = kFluentStatusInsertion
				elif fluent_on_energy < fluent_threshold_on_energy:
					# off to on!
					fluent_hash[fluent_on_name]["energy"] = fluent_on_energy
					fluent_hash[fluent_on_name]["status"] = kFluentStatusOffToOn
					fluent_hash[fluent_off_name]["energy"] = kZeroProbabilityEnergy
					fluent_hash[fluent_off_name]["status"] = kFluentStatusOffToOn
				elif fluent_on_energy > fluent_threshold_off_energy:
					# on to off!
					fluent_hash[fluent_off_name]["energy"] = opposite_energy(fluent_on_energy)
					fluent_hash[fluent_off_name]["status"] = kFluentStatusOnToOff
					fluent_hash[fluent_on_name]["energy"] = kZeroProbabilityEnergy
					fluent_hash[fluent_on_name]["status"] = kFluentStatusOnToOff
				else:
					continue
				# go through all parses that this fluent touches, or its inverse
				for parse_id in parse_id_hash_by_fluent[fluent_on_name] + parse_id_hash_by_fluent[fluent_off_name]:
					if parse_id not in active_parse_trees:
						# create this parse if it's not in our list of active parses
						active_parse_trees[parse_id] = parse_array[parse_id]
					active_parse_trees[parse_id]["frame"] = frame
			# complete any active parse trees that had their "primary" fluent change (or its inverse)
			for fluent in changes:
				for key in active_parse_trees.keys():
					active_parse_tree = active_parse_trees[key]
					if active_parse_tree["symbol"] in (fluent_on_name, fluent_off_name):
						active_parse_trees.pop(key)
						complete_parse_tree(active_parse_tree, fluent_hash, event_hash, frame, completions, 'fluent_changed', event_timeouts)
					elif kFilterNonEventTriggeredParseTimeouts:
						# this is a bug!  this will kill all but the first type of fluent
						# if we want to remove the case of parses timing out when they never
						# actually had an event create them
						raise Exception("@ERROR 0xa888321: this is a bug! WUT!?")
						active_parse_trees.pop(key)
			events_and_fluents_at_frame[frame] = get_energies(fluent_hash, event_hash)
		else:
			frame = action_parse_frames[action_parse_index]
			events_and_fluents_at_frame[frame] = get_energies(fluent_hash, event_hash)
			complete_outdated_parses(active_parse_trees, parse_array, fluent_hash, event_hash, event_timeouts, frame, reporting_threshold_energy, completions)
			changes = action_parses[frame]
			filter_changes(changes, fluent_and_event_keys_we_care_about['events'])
			action_parse_index += 1
			for event in changes:
				info = changes[event]
				# print("SETTING EVENT {} AT {} TO {}".format(event,frame,info['energy']))
				event_hash[event]['energies'].append({'energy':info['energy'],'agent':info['agent'],'frame':frame})
				# print_energies(fluent_hash,event_hash)
				for parse_id in parse_id_hash_by_event[event]:
					if parse_id not in active_parse_trees:
						# create this parse if it's not in our list of active parses
						active_parse_trees[parse_id] = parse_array[parse_id]
					active_parse_trees[parse_id]["frame"] = frame
			events_and_fluents_at_frame[frame] = get_energies(fluent_hash, event_hash)
		wipe_fluent_hash(fluent_hash)
	# clean up
	complete_outdated_parses(active_parse_trees, parse_array, fluent_hash, event_hash, event_timeouts, frame+999999, reporting_threshold_energy, completions)
	if not suppress_output and False:
		import pprint
		pp = pprint.PrettyPrinter(depth=6)
		print "=-==-=-==-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=--="
		pp.pprint(completions)
		print "=-==-=-==-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=--="
	if clever:
		from itertools import izip
		if not suppress_output:
			print("\nLEGEND:")
			print("\tTESTING\tenergy of top-level fluent\tsource/trigger\tprevparse id\tprevparse")
			print("\t...?match/wrong\tprevchain energy\tinstantaneous node energy\n")
			hr()
		for fluent in completions.keys():
			prev_chains = []
			prev_chain_energies = []
			if not suppress_output:
				print("{}".format(fluent))
				hr()
			for frame in sorted(completions[fluent].iterkeys()):
				if not suppress_output:
					print("\n===== frame {} =====".format(frame))
				completion_data = completions[fluent][frame]
				completion_data = add_missing_parses(fluent, fluent_hash, event_hash, frame, completion_data)
				next_chains = []
				next_chain_energies = []
				for node in completion_data:
					global debug_calculate_energy
					if not suppress_output:
						print("TESTING {}".format("\t".join(["{:>4.3f}".format(node['sum']), node['source'], "?->{:d}".format(node['parse']['id']), str(make_tree_like_lisp(node['parse'])), str(node['agents'])])))
						if frame == 0 and super_debug_energies:
							energies = events_and_fluents_at_frame[frame]
							debug_calculate_energy = True
							print("ENERGIES: {}".format(energies))
							calculate_energy(node['parse'], energies,frame=frame,event_timeouts=event_timeouts)
							debug_calculate_energy = False
					# go through each chain and find the lowest energy + transition energy for this node
					best_energy = -1 # not a possible energy
					best_chain = None
					for prev_chain, prev_chain_energy in izip(prev_chains, prev_chain_energies):
						prev_node = prev_chain[-1]
						prev_symbol = prev_node['parse']['symbol'] # TRASH_MORE_on, for example
						# calculate the current node energy based on the previous chain, because events may already have been used
						prev_actions_used = prev_node['actions_used']
						energies = events_and_fluents_at_frame[frame]
						if super_debug_energies:
							#debug_calculate_energy = frame == 5
							debug_calculate_energy = True
						node['energy'] = calculate_energy(node['parse'], energies, prev_actions_used,frame=frame,event_timeouts=event_timeouts)
						debug_calculate_energy = False
						# if this pairing is possible, see if it's the best pairing so far
						# BACKLOG: this function will be changed to get an energy-of-transition
						# which will no longer be "binary"
						matches = False
						if not require_consistency or parse_is_consistent_with_requirement(node['parse'],prev_symbol):
							matches = True
							if best_energy == -1 or best_energy > prev_chain_energy:
								best_energy = prev_chain_energy
								best_node_energy = node['energy']
								best_chain = prev_chain
								#print("PREV: {}".format(prev_node['parse']))
								#print("CONX: {}".format(node['parse']))
						elif parse_can_jump_from(prev_node['parse'],node['parse']):
							# look for timer-based jumps ... so if this node['parse'] has a possible timer jump, let's see it
							print("{}".format(prev_node['parse']))
							print("{}".format(node['parse']))
							raise("HELL...O")
						else:
							pass
						# now we take our best chain for this node, and dump it and its energy in our new list
						if not suppress_output:
							print("{}   {}".format(" +match" if matches else " -wrong","\t".join(["{:>4.3f}".format(prev_chain_energy), "{:>4.3f}".format(node['energy']), "{:d}->{:d}".format(prev_node['parse']['id'],node['parse']['id']), str(make_tree_like_lisp(prev_node['parse'])), str(prev_node['agents'])])))
							if super_debug_energies:
								#print(make_tree_like_lisp_with_energies(prev_node['parse'])), str(prev_node['agents'])])))
								print("{}".format(energies))
					# best_chain should exist for EVERY node for EVERY frame != 0
					if best_chain:
						chain = best_chain[:] # shallow-copies the chain
						actions_used = get_actions_used(node['parse'])
						prev_used = chain[-1]['actions_used']
						events_used = get_energies_used(actions_used, energies[1], prev_used)
						node['my_actions_used'] = events_used # this is so we can get the exact frame for actions used...
						node['actions_used'] = merge_actions_used(prev_used,events_used)
						#print("\t\tactions used: {}".format(node['actions_used']))
						chain.append(node)
						next_chains.append(chain)
						next_chain_energies.append(best_energy + best_node_energy)
						if not suppress_output:
							print(" {}".format("-"*90))
							print(" >best<   {}\n".format("\t".join(["{:>4.3f}".format(best_energy), "{:>4.3f}".format(best_node_energy), "{:d}->{:d}".format(best_chain[-1]['parse']['id'],node['parse']['id']), str(make_tree_like_lisp(best_chain[-1]['parse'])), str(best_chain[-1]['agents'])])))
					else:
						if not prev_chains:
							# this should only happen @ the first frame parse
							energies = events_and_fluents_at_frame[frame]
							events_used = get_energies_used(get_actions_used(node),energies[1])
							node['my_actions_used'] = node['actions_used'] = events_used
							node['energy'] = calculate_energy(node['parse'], energies, node['actions_used'],frame=frame,event_timeouts=event_timeouts)
							#print("ASSIGNING INITIAL ACTIONS USED: {}".format(node['actions_used']))
							next_chains.append([node,])
							next_chain_energies.append(node['energy'])
						else:
							# NO BAD WRONG
							import pprint
							pp = pprint.PrettyPrinter(depth=6)
							print "*** NOTHING FOUND DESPITE {} CHAIN(S) EXISTING".format(len(prev_chains))
							for chain in prev_chains:
								print chain
							print "*** WILL NOT LINK TO"
							pp.pprint(node['parse'])
							raise Exception("NAW")
				prev_chains = next_chains
				prev_chain_energies = next_chain_energies
			# and now we just wrap up our results... 
			chain_results = []
			for chain, energy in izip(prev_chains, prev_chain_energies):
				items = []
				for item in chain:
					items.append((item['frame'],item['parse']['id'],item['my_actions_used']))
				#print([items,energy])
				# tracking total energy as well as "average" energy to normalize for chain length
				chain_results.append([items,float("{:4.3f}".format(energy)),float("{:4.3f}".format(energy/len(items)))])
			# print('\n'.join(['\t'.join(l) for l in chain_results]))
			# and sort our results
			chain_results = sorted(chain_results,key=lambda(k): k[2])[:20]
			results_for_xml_output.append(chain_results[:1])
			# and maybe print them out
			if not suppress_output:
				print('\n'.join(map(str,chain_results)))
				hr()
				hr()
	else: # not clever i.e. brute force
		for fluent in completions.keys():
			prev_chains = []
			if not suppress_output:
				print fluent
				hr()
			for frame in sorted(completions[fluent].iterkeys()):
				completion_data_sorted = sorted(completions[fluent][frame], key=lambda (k): k['energy'])
				if not prev_chains:
					for child in completion_data_sorted:
						prev_chains.append((child,))
				else:
					children = []	
					for prev_chain in prev_chains:
						last_parent_node = prev_chain[-1]
						last_parent_symbol = last_parent_node['parse']['symbol'] # TRASH_MORE_on, for example
						for child in completion_data_sorted:
							# if this pairing is possible, cross it on down
							# pairing is considered "possible" if the parent's primary fluent status agrees with all relevant child fluent pre-requisites
							if not requires_consistency or parse_is_consistent_with_requirement(child['parse'],last_parent_symbol):
								chain = list(prev_chain)
								chain.append(child)
								children.append(chain)
					prev_chains = children
				for completion_data in completion_data_sorted:
					if not suppress_output:
						print("{}".format("\t".join(["{:12d}".format(frame), "{:>4.3f}".format(completion_data['sum']), "{:>4.3f}".format(completion_data['energy']), completion_data['source'], "{:d}".format(completion_data['parse']['id']), str(make_tree_like_lisp(completion_data['parse'])), str(completion_data['agents'])])))
			chain_results = []
			for chain in prev_chains:
				items = []
				energy = 0
				for item in chain:
					items.append((item['frame'],item['parse']['id']))
					energy += item['energy']
				#print([items,energy])
				chain_results.append([items,float("{:4.3f}".format(energy)),float("{:4.3f}".format(energy/len(items)))])
			# print('\n'.join(['\t'.join(l) for l in chain_results]))
			chain_results = sorted(chain_results,key=lambda(k): k[2])[:20]
			results_for_xml_output.append(chain_results[:1])
			if not suppress_output:
				print('\n'.join(map(str,chain_results)))
				hr()
				hr()
	return results_for_xml_output

def build_xml_output_for_chain(all_chains,parse_array,suppress_output=False):
	temporal = ET.Element('temporal')
	fluent_changes = ET.SubElement(temporal,'fluent_changes')
	actions_el = ET.SubElement(temporal,"actions")
	seen = [] # keeping track of whether we've seen a fluent and thus have included its initial state
	for chainx in all_chains:
		#print("CHAINX: {}".format(chainx))
		energy = chainx[0][1]
		chain = chainx[0][0]
		for instance in chain:
			#print("INSTANCE: {}".format(instance))
			frame_number = instance[0]
			parse_id = instance[1]
			events = instance[2]
			parse = parse_array[parse_id]
			# get fluents where there's a prev-fluent and fluent.  or just stick with top level?
			if not suppress_output:
				#print("{}".format(frame_number))
				#print("{}".format(parse['symbol']))
				#print("{}".format(parse))
				pass
			fluent, fluent_value = parse['symbol'].rsplit("_",1)
			fluent_attributes = {
				"fluent": fluent,
				"new_value": fluent_value,
				"frame": str(frame_number),
				"energy": str(energy)
			};
			prev_value = get_prev_fluent_value_from_parse(parse,fluent)
			if len(prev_value) != 1:
				print("{}".format(len(prev_value)))
				print("Parse: {}".format(parse))
				raise Exception("The tree does not have a previous fluent")
			#print("{}".format(prev_value))
			if prev_value[0] != fluent_value:
				fluent_attributes['old_value'] = prev_value[0];
			if prev_value[0] != fluent_value or fluent not in seen:
				fluent_parse = ET.SubElement(fluent_changes, "fluent_change", fluent_attributes)
			if not fluent in seen:
				seen.append(fluent,)
			# BACKGLOG: missing attributes id, object, time in fluent_change
			# now let's see if there's an action associated with this fluent change and pop that in our bag
			actions = get_actions_from_parse(parse)
			if actions:
				# serious unpacking here
				chainx_actions = {y[0][0]:y[0][1] for y in [[[z,list(y[2][z])[0]] for z in y[2]] for y in chainx[0][0]] if y != []}
				for action in actions:
					#action_frame = chainx_actions[action] if action in chainx_actions else frame_number
					action_frame = list(events[action])[0] if action in events else frame_number
					action_el = ET.SubElement(actions_el,"event", {
						"frame": str(action_frame),
						"energy": str(energy),
						"action": str(action),
					});
	return temporal

# WARNING: this assumes we're only going to find one previous fluent value for the given fluent
def get_prev_fluent_value_from_parse(parse,fluent):
	prev_fluents = []
	# get prev fluent
	if "symbol_type" in parse:
		if parse["symbol_type"] == "prev_fluent":
			tmp_fluent, tmp_fluent_value = parse["symbol"].rsplit("_",1)
			#print("11111")
			if tmp_fluent == fluent:
				#print("2221222")
				prev_fluents.append(tmp_fluent_value)
				#print("{}".format(prev_fluents))
	if "children" in parse:
		for child in parse["children"]:
			child_prev_fluents = get_prev_fluent_value_from_parse(child,fluent)
			prev_fluents += child_prev_fluents
	return prev_fluents

def get_actions_from_parse(parse):
	actions = []
	if "symbol_type" in parse:
		if parse["symbol_type"] == "event":
			#tmp_event, tmp_event_value = parse["symbol"].rsplit("_",1)
			actions.append(parse["symbol"])
	if "children" in parse:
		for child in parse["children"]:
			child_actions = get_actions_from_parse(child)
			actions += child_actions
	return actions

if __name__ == '__main__':
	# WHOO!
	import demo
