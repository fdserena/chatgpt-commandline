# copyright 2024 CogNueva, Inc

import io
import os
import os.path
from os import close, listdir
from os.path import isfile, join
import sys
from openai import OpenAI
import json
import hashlib
from IPython.display import display
import time
import argparse
from argparse import Namespace
import ast
import inspect
import base64
import threading
from threading import Thread, Lock, Semaphore, RLock, Condition, Barrier
import atexit
import shlex
import re

#-------------------------------------------------
# recursive lock for the following 4 values
global_osthread_lock=RLock()
#---------- these are protected by the above recursive lock ---------------
global_osthreadid_counter = 0
global_config_dictnum = 0
# array of [threadinfo,idnumber,Lock, bool_deleted, bool_exited, file_logger] 
#	negative idnumber indicates deletion in place
global_thread_list = []
global_deletion_list = [] # index 0 is the deleting thread ID. 
						  # the remaining indicies are the 
						  # threads being deleted
global_parallel_execution_list=[]  # implmenting parallel execution
global_fatal_error=False  # causes main thread to sys.exit() if True
						  # TODO implement
global_talk_pair=[]		  # contains [threadthattriggered, talktheard1, talkthread2, depth, depth_count, which_thread]  
						  # will be a graph for talk later
global_c=set()
global_parallel_proceed=-1
global_parallel_proceed_condition=Condition(global_osthread_lock)
global_deletion_condition=Condition(global_osthread_lock)
global_write_to_msg_buffer=False
#-------------------------------------------------------
#-------------------------------------------------------
# these do not require extra sychronization: 
global_get_input_lock=Lock()  # gets input without interleaving
# lock display to one thread for longer messages
# so they don't interleave
global_message_display_lock=Lock()
# main must create a thread in calling mainx
# this is the signal to make a thread
global_make_a_new_thread_lock=Lock()

# no synchronization needed here
# set when program starts
global_main_thread=None
#-------------------------------------------------------
global_line_continuation_character="#"
# global_long_line_lock=Lock()  # for windows length buffer of stdout truncating str(input())
#-------------------------------------------------------

class ThreadArray():
	INFO = 0
	ID = 1
	DICTNUM = 2
	LOCK = 3 
	BOOL_DELETED = 4 
	BOOL_EXITED = 5 
	READABLE_NAME = 6 
	SANDBOX_FILE_ID_LIST = 7
	TD = 8 
	BOOL_FATAL_ERROR = 9 

class ThreadCrossTalk():
	THREAD_TO_RETURN_TO= 0
	THREAD1 = 1
	THREAD2 = 2 
	MAX_DEPTH = 3 
	CURRENT_DEPTH = 4 
	SEED_DEPTH = 5	 # input get manual msg seeds while CURRENT_DEPTH<SEED_DEPTH 
	MSG = 6 

def find_thread_record(where_to_write=sys.__stdout__):
	# LOCK this assumed on entry -- global global_osthread_lock
	global global_osthread_lock
	global global_thread_list

	global_osthread_lock.acquire()
	integrity_check()

	ident=threading.current_thread().ident	

	for i,j in enumerate(global_thread_list):
		if j[ThreadArray.INFO].ident == ident:
			global_osthread_lock.release()
			return i 

	global_osthread_lock.release()
	return None

def find_first_active_thread():
	global global_osthread_lock
	global global_thread_list 

	global_osthread_lock.acquire()
	integrity_check()

	for i,j in enumerate(global_thread_list):
		if j[ThreadArray.BOOL_EXITED]==True:
			continue
		if j[ThreadArray.BOOL_DELETED]==True:
			continue
		global_osthread_lock.release()
		return i 

	global_osthread_lock.release()
	return None 

def deletion_condition(thread_numbers):
	global global_osthread_lock
	global global_thread_list

	if thread_numbers==[]:
		return True

	global_osthread_lock.acquire()
	for v in thread_numbers:
		if global_thread_list[v][ThreadArray.BOOL_EXITED]==False:
			global_osthread_lock.release()
			return False 

	global_osthread_lock.release()
	return True 

def is_valid_thread(thread):
	try:
		if thread<0 or thread>=len(global_thread_list) or global_thread_list[thread][ThreadArray.BOOL_DELETED]==True:
			print(f"invalid thread number {thread}.")
			return False
	except:
		return False
	return True	

class ThreadLogger(object):
	input_lock=RLock()
	thread_structure_lock=RLock()
	thread_info_dictionary={}
	terminal=sys.__stdout__

	def __init__(self):
		ThreadLogger.terminal=sys.__stdout__
		if threading.current_thread().ident==threading.main_thread():
			ThreadLogger.thread_structure_lock.acquire()
			ThreadLogger.thread_info_dictionary={}
			ThreadLogger.thread_structure_lock.release()
		return None

	@staticmethod
	def add(osthreadid, thread_directory, log_file_name):
		if threading.current_thread().ident==threading.main_thread():
			return None

		# make thread directory if it doesn't exist
			# make directory for files
		try:
			os.mkdir(thread_directory)
			ThreadLogger.terminal.write(f"Directory '{thread_directory}' created")
		except:
			ThreadLogger.terminal.write(f"Directory '{thread_directory}' already exists")

		temp_full_path_to_logfile = os.path.join(thread_directory, log_file_name)
		file_handle = open(temp_full_path_to_logfile, "w", encoding = "utf-8")

		ThreadLogger.thread_structure_lock.acquire()

		try:
			if ThreadLogger.thread_info_dictionary.get(threading.current_thread().ident,None)==None:
				pass
			else:
				ThreadLogger.thread_info_dictionary[threading.current_thread().ident].close()

			ThreadLogger.thread_info_dictionary[threading.current_thread().ident]=file_handle
		except:
			ThreadLogger.thread_info_dictionary[threading.current_thread().ident]=None

		ThreadLogger.thread_structure_lock.release()

	@staticmethod
	def close():
		ThreadLogger.thread_structure_lock.acquire()

		try:
			if ThreadLogger.thread_info_dictionary.get(threading.current_thread().ident,None)==None:
				pass
			else:
				ThreadLogger.thread_info_dictionary[threading.current_thread().ident].close()
		except:
			ThreadLogger.thread_info_dictionary[threading.current_thread().ident]=None

		ThreadLogger.thread_structure_lock.release()

	def read(self, message):
		#self.terminal_in.read()
		return	

	def flush(self):
		ThreadLogger.terminal.flush()

		if threading.current_thread().ident==threading.main_thread():
			return

		ThreadLogger.input_lock.acquire()
		ThreadLogger.thread_structure_lock.acquire()

		try:
			if ThreadLogger.thread_info_dictionary.get(threading.current_thread().ident,None)==None:
				pass
			else:
				ThreadLogger.thread_info_dictionary[threading.current_thread().ident].flush()
		except:
			ThreadLogger.thread_info_dictionary[threading.current_thread().ident]=None

		ThreadLogger.thread_structure_lock.release()
		ThreadLogger.input_lock.release()

	def write(self, message):
		global global_write_to_msg_buffer

		if global_write_to_msg_buffer:
			global_talk_pair[ThreadCrossTalk.MSG]+=message

		ThreadLogger.terminal.write(message)
		ThreadLogger.terminal.flush()

		if threading.current_thread().ident==threading.main_thread():
			return

		ThreadLogger.input_lock.acquire()
		ThreadLogger.thread_structure_lock.acquire()

		try:
			if ThreadLogger.thread_info_dictionary.get(threading.current_thread().ident,None)==None:
				pass
			else:
				ThreadLogger.thread_info_dictionary[threading.current_thread().ident].write(message)
				ThreadLogger.thread_info_dictionary[threading.current_thread().ident].flush()
		except:
			ThreadLogger.thread_info_dictionary[threading.current_thread().ident]=None

		ThreadLogger.thread_structure_lock.release()
		ThreadLogger.input_lock.release()

	@staticmethod
	def get_input(message):
		''' for windows buffer limit "bug" '''
		rval="" 
		ThreadLogger.input_lock.acquire()
		prev=sys.stdout
		sys.stdout=sys.__stdout__
		rval=str(input(message)) 
		sys.stdout=prev
		ThreadLogger.input_lock.release()

		return rval 

def show_json(obj):
	display(json.loads(obj.model_dump_json()))

def wait_on_run(client, run, thread):
	while run.status == "queued" or run.status == "in_progress":
		run = client.beta.threads.runs.retrieve(
			thread_id=thread.id,
			run_id=run.id,
		)
		time.sleep(0.5)
	return run

def display_message(client, message):
	# Extract the message content
	try:
		message_content = message.content[0].text
		annotations = message_content.annotations
	except:
		print("\n---------------------------------------\n")
		print("No utf-8 text type in message and/or annotations.")
		print("\n---------------------------------------\n")
		return

	citations = []
	
	# Iterate over the annotations and add footnotes
	for index_citations, annotation in enumerate(annotations):
		# Replace the text with a footnote
		message_content.value = message_content.value.replace(annotation.text, f' [{index_citations}]')

		try:
			# Gather citations based on annotation attributes
			if (file_citation := getattr(annotation, 'file_citation', None)):
				cited_file = client.files.retrieve(file_citation.file_id)
				citations.append(f'[{index_citations}] {file_citation.quote} from {cited_file.filename}')
			elif (file_path := getattr(annotation, 'file_path', None)):
				cited_file = client.files.retrieve(file_path.file_id)
				citations.append(f'[{index_citations}] Click <here> to download {cited_file.filename}')
				# Note: File download functionality not implemented above for brevity
		except:
			print("error: citations")
			citations=[]
			# continue
	
	# Add footnotes to the end of the message before displaying to user
	#   message_content.value += '\n' + '\n'.join(citations)
	#print(citations)
	print("\n----------------------------------\n")
	#	pretty_print(m)
	#	show_json(m)
	print(message_content.value.encode("utf-8").decode('unicode-escape', errors='ignore'))
	#print(m.content[0].text.value)
	print("\n----------------------------------\n")
	
	#print()
	print("\n++++++++++++++++++++++++++++++++++\n")

	for c in citations:
		print(c.encode("utf-8").decode('unicode-escape', errors='ignore'))
		
	print("\n++++++++++++++++++++++++++++++++++\n")
	return

def string_base16filename(name):
	if name==None:
		name=""
	h = hashlib.new('sha256')#sha256 can be replaced with diffrent algorithms
	h.update(name.encode()) #give a encoded string. Makes the String to the Hash
	fname=h.hexdigest()
	return fname

def string_base64filename(name):
	if name==None:
		name=""
	s=base64.b64encode(hashlib.sha256(name.encode()).digest()).decode()
	d=""
	for c in s:
		if c=="+":
			c="-"
		elif c=="/":
			c="_"
		elif c=="=":
			c="="   # lossy if not "=" 
					# one may put anything allowed in a filename
					# and not in base64 + "-" + "_"
		else:
			pass

		d=d+c
	return d	
	

def get_temp_id_filename(name):
	fname=string_base64filename(name)
	fname=fname+".assistant-files.ids"
	return fname

def get_temp_directory(name, osthreadid):
	fname=string_base64filename(name)
	fname=fname+"."+str(osthreadid)+".directory"
	return fname

def file_cleanup(client, fids_up, exit_val=False):
	if len(fids_up)!=0:
		print(f"Removing files:")
	for fid in fids_up:
		print(f"Deleting file {fid}")
		try:
			client.files.delete(fid)
		except:
			print(f"File {fid} not there or not deleted")
	if exit_val:
		print("Exiting")
		sys.exit()
	return
	
# returns assistant file id
def open_assistant(namespace, client, name, purpose_narrative="", 
		file_list=[], tools=[{"type": "code_interpreter"},{"type": "retrieval"}], 
		osthreadid=0):
	fname=get_temp_id_filename(name)

	# make directory for files
	td=get_temp_directory(name, osthreadid)
	try:
		os.mkdir(td)
		print(f"Directory '{td}' created")
	except:  # put OSError here TODO
		print(f"Directory '{td}' already exists")

	try:
		assistant_file=open(fname, "r")
	except OSError:
		print("Uploading Files")
		fid_id_list = []
		for index_file,f in enumerate(file_list):
			try:
				print(f"Opening file: '{f}'")
				temp=open(f, "rb")
#				print(temp.read())
			#except OSError:
			except:
				print(f"File '{f}' does not exist or can't be read. Exiting")
				# cleanup files that have already been uploaded
				file_cleanup(client, fid_id_list, exit_val=True)
			try:
				file1 = client.files.create( file=temp, purpose='assistants') 
			except:	
				print(f"Openai error uploading file '{f}'.")
				file_cleanup(client, fid_id_list, exit_val=True)
				
			temp.close()

			fid_id_list.append(file1.id)
			print(f"'{f}' file uploaded as {file1.id}.")
		print("Creating assistant")
		try:
			assistant = client.beta.assistants.create(
			  name=name,
			  description=purpose_narrative,
			  model="gpt-4-1106-preview",
			  tools=tools,
			  file_ids=fid_id_list
			)
		except:
			# delete the uploaded files
			# then exit the program
			print("Assistant creation failed")
			file_cleanup(client, fid_id_list, exit_val=True)

		print(f"purpose_narrative: {purpose_narrative}")
	# write out id 
		afile=open(fname, "w")
		print(f"{assistant.id}")
		afile.write(f"{assistant.id}\n")
		for fid in fid_id_list: 
			afile.write(f"{fid}\n")
		afile.close()
		assistant_file_id=assistant.id
	else:
		start=1
		fid_id_list=[]
		with assistant_file as f:
			for line in f:
				if start==1: 
					assistant_file_id=line.strip(' \t\n\r')
					start=0 
				else: 
					fid_id_list.append(line.strip(' \t\n\r'))
		assistant_file.close() 
	return (assistant_file_id, fid_id_list)

def concatenate_list(lst):
	rval=" "
	for j in lst:
		rval=rval+str(j)+" "
	rval=rval.strip(" \"'")
	return rval

def create_parser():
	parser = argparse.ArgumentParser(prog='+',
					description='+ command line functionality',
					epilog='+ command line fuctionality',
					prefix_chars='-')

	valid_subparser_list=['quit', 'quit_all', 'raw_list', 'list', 'list_all',
			'get_local', 'get_all', 'list_local', 'delete_local', 
			'new_thread', 'list_thread', 'switch_thread', 
			'delete_thread', 'name_thread', 'parallel_run', 
			'join2_thread', 'new_asst']

	subparsers = parser.add_subparsers(title='subcommands',
								   description='valid subcommands',
								   help='additional help',
								   required=False,
								   metavar=set(valid_subparser_list))

	parser_raw_list = subparsers.add_parser('raw_list', 
			help='shows raw list information of remote file')
	parser_raw_list.set_defaults(rawx=True)

	parser_list = subparsers.add_parser('list', help="lists the remote files")
	parser_list.set_defaults(listx=True)

	parser_list_all = subparsers.add_parser('list_all', help="lists the remote files across multiple threads")
	parser_list_all.set_defaults(list_allx=True)

	parser_get_local= subparsers.add_parser('get_local', help="gets remote files locally")
	parser_get_local.set_defaults(get_localx=True)

	parser_get_all= subparsers.add_parser('get_all', help="gets ALL thread, remote files locally")
	parser_get_all.set_defaults(get_allx=True)

	parser_delete_local= subparsers.add_parser('delete_local', help="delete files in local directory, but not the log.txt file.")
	parser_delete_local.set_defaults(delete_localx=True)
	
	parser_list_local= subparsers.add_parser('list_local', help="list (ls) local directory. files only.")
	parser_list_local.set_defaults(list_localx=True)
	
	parser_new_thread= subparsers.add_parser('new_thread', help="create new thread")
	parser_new_thread.add_argument('-c', '--config', metavar='config_file_number', type=int, nargs='?',
					help='add and optional conif number')
	parser_new_thread.set_defaults(new_threadx=True)
	
	parser_list_thread= subparsers.add_parser('list_thread', help="list thread")
	parser_list_thread.set_defaults(list_threadx=True)

	parser_delete_thread= subparsers.add_parser('delete_thread', help="quits thread number")
	parser_delete_thread.add_argument('thread_numbers', metavar='t_for_deletion', type=int, nargs='+',
					help='deletes specified thread numbers. thread will "+ quit" to exit gracefully.')
	parser_delete_thread.set_defaults(delete_threadx=True)

	parser_switch_thread= subparsers.add_parser('switch_thread', help="switch thread to a valid integer")
	parser_switch_thread.add_argument('thread_number', metavar='t_to_switch', type=int, 
					help='switch to a specified thread number.')
	parser_switch_thread.set_defaults(switch_threadx=True)

	parser_quit = subparsers.add_parser('quit', help="quit the thread you are on.")
	parser_quit.set_defaults(quitx=True)

	parser_quit_all = subparsers.add_parser('quit_all', help="quit all threads that are active")
	parser_quit_all.set_defaults(quit_allx=True)

	parser_parallel_run= subparsers.add_parser('parallel_run', help="runs the named thread by thread number")
	parser_parallel_run.add_argument('thread_numbers', metavar='t_for_parallel_execution', type=int, nargs='+',
					help='goes into parallel run mode on thread numbers supplied. Existing thread always participates.')
	parser_parallel_run.set_defaults(parallel_runx=True)

	parser_join2_thread= subparsers.add_parser('join2_thread', help="joins 2 threads with conversation 'seeds'")
	parser_join2_thread.add_argument('thread_numbers', metavar='t_for_thread_2_join', type=int, nargs='+',
					help='goes into parallel run mode on the two named (accessed by thread number) threads. Threads are joined in a conversation')
	parser_join2_thread.add_argument('-d', '--depth', default=5, type=int, nargs=1, metavar='maximum conversation depth assumed 5')
	parser_join2_thread.add_argument('-s', '--seed', default=2, type=int, nargs=1, metavar='seed values for starting cross talk.')
	parser_join2_thread.set_defaults(join2_threadx=True)

	parser_name_thread= subparsers.add_parser('name_thread', help="names the current active thread")
	parser_name_thread.add_argument('thread_name', type=str, metavar='readable_thread_name', nargs=1)
	parser_name_thread.set_defaults(name_threadx=True)

	# TODO implement this	
	parser_new_asst= subparsers.add_parser('new_asst', help="create new assistant")
	# with -c a new assistant is copied from another assistant's configuration
	parser_new_asst.add_argument('-c', '--config', metavar='config_file_number', type=int, nargs=1,
					help='add an optional configuration number')
	parser_new_asst.set_defaults(new_asstx=True)
	
	return parser

def file_list(client, thread, messages):
	file_list=[]
	for m in messages:
		message_files_previous=None
		while True:
			if message_files_previous!=None:
				message_files = client.beta.threads.messages.files.list(
					thread_id=thread.id,
					message_id=m.id,
					limit=1,
					after=message_files_previous
					)
			else:
				message_files = client.beta.threads.messages.files.list(
					thread_id=thread.id,
					message_id=m.id,
					limit=1
				)

			try:
				clear_name=client.files.retrieve(message_files.data[0].id).filename
				file_list.append([message_files.data[0].id,clear_name])
			except:
				break
	
			if message_files.has_more:
				message_files_previous=message_files.last_id
			else:
				break
	return file_list
	

def raw_list(client, thread, messages):
	# raw_list
	for m in messages:
		message_files_previous=None
		while True:
			if message_files_previous!=None:
				message_files = client.beta.threads.messages.files.list(
					thread_id=thread.id,
					message_id=m.id,
					limit=10,
					after=message_files_previous
					)
			else:
				message_files = client.beta.threads.messages.files.list(
					thread_id=thread.id,
					message_id=m.id,
					limit=10
				)
	
			print(message_files)
	
			if message_files.has_more:
				message_files_previous=message_files.last_id
			else:
				break
	return

def get_sandbox_remote_file(client,
		i,file,
		temp_directory,
		sandbox_files_id_set): # of course sandbox_files_id_set passed by reference

	sandbox_file_id=file[0]
	local_file_name=os.path.split(file[1])[-1]
	current_directory=os.getcwd()
	file_to_write=os.path.join(current_directory,temp_directory,local_file_name)
	try:
		contents_of_sandbox_file_data=client.files.content(sandbox_file_id)
		contents_of_sandbox_file_bytes = contents_of_sandbox_file_data.read()
		contents_of_sandbox_file = io.BytesIO(contents_of_sandbox_file_bytes) 

		'''
			*** Useful code ***
				#contents_of_sandbox_file=client.files.retrieve_content(sandbox_file_id)
		# Example
		#file_data = client.files.content(first_file_id)
		#file_data_bytes = file_data.read()
		#file_like_object = io.BytesIO(file_data_bytes)
		
				#print(f"contents is {contents_of_sandbox_file}")
				#print(f"writing contents {contents_of_sandbox_file} to {file_to_write}")
				#contents_of_sandbox_file=client.files.content(sandbox_file_id)
				#contents_of_sandbox_file=client.beta.files.content(sandbox_file_id)
				#fo.write(contents_of_sandbox_file.encode())#.encode("utf-8"))
				#fo.write(contents_of_sandbox_file)#.encode("utf-8"))
				#print(f"{contents_of_sandbox_file.encode()}", sep='', flush=True, end="", file=fo)
				#print(contents_of_sandbox_file.getvalue(), sep='', flush=True, end="", file=fo)
		'''
		
		fo=open(file_to_write,"wb")
		#print(f"type of contents is {type(contents_of_sandbox_file)}")
		print(f"writing contents to {local_file_name}")
		fo.write(contents_of_sandbox_file.getvalue())
		fo.close()
		contents_of_sandbox_file.close()
	except:
		sandbox_files_id_set.remove(sandbox_file_id)
		print(f"in get_local sandbox file '{file}' not retrieved")
	return

def scan_messages_for_sandbox_files(osthreadid, client, 
		thread, messages, 
		sandbox_files_id_set):
	# always collect valid sandbox files
	# TODO file may be renamed in the sandbox
	f=file_list(client, thread, messages)
	#print(f"{f}\nset={set(map(lambda x: x[0],f))}")
	rval_sandbox_files_id_set=sandbox_files_id_set.union(set(map(lambda x: x[0],f))).copy()

	# remove those that are no longer there in the sandbox from sandbox_files_id_set
	temp=rval_sandbox_files_id_set.copy()

	for f2 in temp:
		try:
			r=client.files.retrieve(f2)
			if str(type(r))!="<class 'openai.types.file_object.FileObject'>" or r==set() or r==None:
				rval_sandbox_files_id_set.remove(f2)
				print(f"r={r} file id = {f2}\n No longer there\n")
		except:
			rval_sandbox_files_id_set.remove(f2)
			print(f"* file id = {f2}\n No longer there\n")

	sandbox_files_id_list=list(rval_sandbox_files_id_set)
	#print(f"sandbox ids={sandbox_files_id_list}")
	sandbox_file_paired_with_sandbox_name_list=[]
	
	# get sandbox name
	for vv_ids in sandbox_files_id_list:
		try:
			clear_name=client.files.retrieve(vv_ids).filename
			sandbox_file_paired_with_sandbox_name_list.append([vv_ids,clear_name])
		except:
			print(f"File '{vv_ids}' file meta information not retrievable")
			continue

	# for interthread transfers to another assistant
	global_osthread_lock.acquire()
	global_thread_list[osthreadid][ThreadArray.SANDBOX_FILE_ID_LIST]=sandbox_file_paired_with_sandbox_name_list.copy()
	global_osthread_lock.release()

	#print(f"List of remote sandbox files as pairs (id, name): {sandbox_file_paired_with_sandbox_name_list}")
	return sandbox_file_paired_with_sandbox_name_list, rval_sandbox_files_id_set

def make_locals(dict1, thread_local_storage):
	triple_quotes=re.compile(".*(''')+.*")
	triple_double_quotes=re.compile('.*(""")+.*')
	for i in dict1:
#		print(f"{i=} {dict1[i]}")
		r= (triple_quotes.match(f"{dict1[i]}")==None)
		s= (triple_double_quotes.match(f"{dict1[i]}")==None)
		if not r and not s:
			print("Error in configuration file.  Use \'\'\' or \"\"\" but not both")
			v=""
		elif s:  # triple single quotes used
			if type(dict1[i])==str:
				v=f'''thread_local_storage.{i}="""{dict1[i]}"""''' 
			else:
				v=f"""thread_local_storage.{i}={dict1[i]}""" 
		elif r:  # triple double quotes used
			if type(dict1[i])==str:
				v=f"""thread_local_storage.{i}='''{dict1[i]}'''"""
			else:
				v=f'''thread_local_storage.{i}={dict1[i]}''' 
		else:	# neither triple quotes used
			if type(dict1[i])==str:
				v=f"""thread_local_storage.{i}='''{dict1[i]}'''"""
			else:
				v=f'''thread_local_storage.{i}={dict1[i]}''' 
		#print(v)
		exec(v) 

def dele(namespace):
	client = OpenAI()
	thread=dict()
	# single threaded "delete"
 
	mloc=threading.local()
	config_dict_list=get_config_dict(namespace)

	for j in range(0, len(config_dict_list)):
		# what to do without threading
		#sys._getframe(len(inspect.stack(0))-1).f_locals.update(config_dict)
		make_locals(config_dict_list[j], mloc)
		
		# not multithreaded
		print(f"assistant_name='{mloc.assistant_name}'")
		print("Deleting Files and Assistant from Remote Openai")
		# remove assistant and associated files
		fname=get_temp_id_filename(mloc.assistant_name)
		assistant_file_id="NONE"
		try:
			assistant_file=open(fname, "r")
		except:
			print(f"The data file: '{fname}' not found")
			# single threaded with main thread
			# this works
			continue
		start=1
		file_id_list=[]
		with assistant_file as f:
			for line in f:
				if start==1:
					assistant_file_id=line.strip(' \t\n\r')
					start=0
				else:
					file_id_list.append(line.strip(' \t\n\r'))
		assistant_file.close()
		file_cleanup(client, file_id_list, exit_val=False) 
		print(f"Deleting Assistant id {assistant_file_id}")
		try:
			client.beta.assistants.delete(assistant_file_id)
		except:
			print(f"Assistant {assistant_file_id} not there or not deleted")
	
		if namespace.p:
			print("to delete the base deletion file type capital \"Y\":", end='')
			val=str(input(""))
		else:
			val="Y"
	
		if val=="Y":
			os.unlink(fname)
	
	return	# single threaded exit


def exit_condition():
	return number_of_active_threads() == 0

def main(namespace):
	#--------- the following globals are protected by the lock ----------------
	global global_osthread_lock
	global global_osthreadid_counter 
	global global_config_dictnum
	global global_thread_list 
	global global_message_display_lock
	global global_get_input_lock
	global global_make_a_new_thread_lock
	global global_main_thread

	client = OpenAI()
	thread=dict()  # not os thread OpenAi thread

	global_main_thread=threading.main_thread()

	# only main thread here	just started
#	if global_main_thread!=threading.current_thread():
#		print("Not on main thread. Exiting")
#		# should not be reached
#		sys.exit()
#
	skipval=False
	global_make_a_new_thread_lock.acquire()
	global_osthread_lock.acquire()
	sys.stdout=ThreadLogger()
	while True:
		if not skipval:
			try:
				t = threading.Thread(target=mainx, args=(namespace, 
					client, 
					thread, 
					global_osthreadid_counter,
					global_config_dictnum)) 
			except:
				sys.__stdout__.write(f"\nA:{global_config_dictnum} Thread {global_osthreadid_counter} not created. Exiting.\n")
				global_osthreadid_counter -= 1
				global_osthread_lock.release()
				# in main thread TODO check
				sys.exit()	
			else:
				global_thread_list.append([t, global_osthreadid_counter, global_config_dictnum, Lock(), False, False, "",[],"",False])
				global_osthread_lock.release()
		
				t.start()
				   
		# only main thread here 
		# stopgap TODO
		if not global_make_a_new_thread_lock.acquire(blocking=True, timeout=1.0):
			if exit_condition():
				break
			skipval=True
			continue
		else:
			skipval=False
			sys.__stdout__.write("\n*** making thread ***\n")
			global_osthread_lock.acquire()
			global_osthreadid_counter += 1

	sys.stdout=sys.__stdout__
	print("--- End main() ---") 

	return


def default_for_missing_keys(dict1,dict_def):
	for j in dict_def:
		dict1.setdefault(j, dict_def[j])
	return


def default_asst():
	return {
		"assistant_name": "template name 1.0 temp",
		"purpose": "generic purpose",
		"files": [],
		"file_ids": [],
		"tools": [{"type": "code_interpreter"},{"type": "retrieval"}],
		"final_message": "please delete the files in the sandbox",
		"msg_preamble": "",
		"echo_output_file": "default",
	}


def new_asst(namespace, namespace2):

	config_dict_list=get_config_dict(namespace) 
	



def get_config_dict(namespace):
	# *** IMPORTANT *** config_dict values become local variables in the single threaded context
	#  and globals in the multithreaded context
	# don't have any local and global variables that conflict
	# respectively ... conflict or the local/global variable will dominate the value!!!

	# default values they will become local variables
	# do not name anything as them or they will not take the value
	config_dict_default = default_asst()
	config_dict_list=[]

	# read configuration data if flag is present
	if namespace.c!=None: 
		if (clen:=len(namespace.c))>0:
			for j in range(0,clen):
				if namespace.c[j]!="" and namespace.c[j]!="default":
					try:
						config_dict_file=open(namespace.c[j], "r")
						config_contents=config_dict_file.read()
						config_dict_file.close()
						config_dict_list.append(ast.literal_eval(config_contents))
						default_for_missing_keys(config_dict_list[j],config_dict_default)
					except:
						sys.__stdout__.write(f"\nconfiguration file '{namespace.c[j]}' not readable using default values.\n")
						config_dict_list.append(config_dict_default)
				elif namespace.c[j]=="default":
					sys.__stdout__.write(f"\nconfiguration file '{namespace.c[j]}' directing to use default values.\n")
					config_dict_list.append(config_dict_default)
				else:  # namespace.c[j]=="" 
					sys.__stdout__.write(f"\nconfiguration file '{namespace.c[j]}' not readable using default values.\n")
					config_dict_list.append(config_dict_default)
		else: # clen==0
			sys.__stdout__.write(f"\nconfiguration file '{namespace.c[j]}' not readable using default values.\n")
			config_dict_list.append(config_dict_default)
	else:
		config_dict_list.append(config_dict_default)

  
	return config_dict_list

def number_of_active_threads():
	global global_osthread_lock
	global global_thread_list 

	global_osthread_lock.acquire()
	i=0
	integrity_check()

	for j in global_thread_list:
		if j[ThreadArray.BOOL_EXITED]==False:  # exited counts 
			i += 1

	global_osthread_lock.release()
	return i

def get_msg(osthreadid, config_dictnum):
	msg=""
	first_msg=True
	while True:
		if first_msg:
			first_msg=False
			#msg1 = str(input(""))
			msg1=ThreadLogger.get_input("")
			if msg1==global_line_continuation_character:
				msg=""
				break
		else:
			#msg1 = str(input(f"more input ('{global_line_continuation_character}' alone ends): "))
			msg1 = ThreadLogger.get_input(f"more input ('{global_line_continuation_character}' alone ends or any other character ending (A:{config_dictnum} Thread {osthreadid})): ")

		if len(msg1)==0:
			continue
		elif msg1==global_line_continuation_character:
			break
		elif msg1[-1]!=global_line_continuation_character:
			msg=msg+msg1
			break
		else:
			msg = msg + msg1[:-1]

	return msg


def integrity_check():
	#--------- the following globals are protected by the lock ----------------
	global global_osthread_lock
	#---------- these are protected by the above recursive lock ---------------
	global global_osthreadid_counter 
	global global_thread_list 
	global global_deletion_list
	global global_c
	global global_fatal_error 
	#--------------------------------------------------------------------------

	global_osthread_lock.acquire()
	if global_thread_list==[]:
		print("No threads. Error. Exiting")
		global_osthread_lock.release()
		# TODO sys.exit doesn't work in threads
		#thread.exit()
		sys.exit()
	global_osthread_lock.release()
	return True

def input_prompt(osthreadid,parallel,get_cross_talk, config_dictnum):
	#print(f"Line continuation character is '{global_line_continuation_character}' it allows longer input when constrained.")
	global_osthread_lock.acquire()
	if parallel:
		print(f"{global_parallel_execution_list} PARALLEL:::", end='', flush=True)
	if get_cross_talk:
		print(f"{global_talk_pair[ThreadCrossTalk.THREAD1:ThreadCrossTalk.THREAD2+1]} CONVERSATION SEED:::", end='', flush=True)
	if global_thread_list[osthreadid][ThreadArray.READABLE_NAME]!="":
		print(f"Input User Message (A:{config_dictnum} Thread {osthreadid} \tname='{global_thread_list[osthreadid][ThreadArray.READABLE_NAME]}'): ", end='', flush=True)
	else:
		print(f"Input User Message (A:{config_dictnum} Thread {osthreadid}): ", end='', flush=True)
	global_osthread_lock.release()


def loop_construct(osthreadid, config_dictnum):
	global global_osthread_lock
	global global_thread_list
	global global_parallel_execution_list
	global global_c
	global global_parallel_proceed

	parallel=False
	get_cross_talk=False 
	skip_command_processing=False
	skip_input=False

	#try:
	global_osthread_lock.acquire()
	# acquire lock for this thread
	val_thread_list_lock=global_thread_list[osthreadid][ThreadArray.LOCK]
	global_osthread_lock.release()

	# threads wait here until released
	# on their appointed lock
	val_thread_list_lock.acquire()

	global_osthread_lock.acquire()
	thread_is_ending=global_thread_list[osthreadid][ThreadArray.BOOL_DELETED]
	if thread_is_ending:
		# thread is ending
		global_osthread_lock.release()
		val_thread_list_lock.release() 
		print(f"\nExit in thread {osthreadid}")
		# the thread lock is now irrelevant
		# we are quitting the thread
		# not needed:  val_thread_list_lock.acquire() 
		msg = "+ quit"
		return msg, parallel, get_cross_talk, skip_command_processing

	if osthreadid in global_parallel_execution_list:
		parallel=True
		skip_command_processing=True
		global_parallel_proceed=len(global_parallel_execution_list)
	else:
		parallel=False
		global_parallel_proceed=-1

	if global_talk_pair != []:
		get_cross_talk=True
		# 
		if global_talk_pair[ThreadCrossTalk.SEED_DEPTH]<=global_talk_pair[ThreadCrossTalk.CURRENT_DEPTH]:
			skip_input=True
			pass
		else:
			#skip_input=False
			pass

	global_osthread_lock.release()

	if not skip_input:
		global_get_input_lock.acquire()
		input_prompt(osthreadid, parallel, get_cross_talk, config_dictnum)
		msg = get_msg(osthreadid,config_dictnum)
		global_get_input_lock.release()
	else:
		if get_cross_talk:
			msg=global_talk_pair[ThreadCrossTalk.MSG]
		pass

	val_thread_list_lock.release() 

	# get all parallel inputs
	# then release all threads for run
	if parallel:
		global_osthread_lock.acquire()
		global_c.add(osthreadid)
		global_parallel_proceed-=1
		val_thread_list_lock.acquire()
		if (global_parallel_proceed!=0):
			pass
		else:
			global_parallel_proceed_condition.notify_all()

		global_parallel_proceed_condition.wait_for(lambda : global_parallel_proceed==0)
		global_osthread_lock.release()
	else:
		pass

	return msg, parallel, get_cross_talk, skip_command_processing

# multithreaded entry point
def mainx(namespace, client, thread, osthreadid=0, config_dictnum=0):

	#--------- the following globals are protected by the lock ----------------
	global global_osthread_lock
	#---------- these are protected by the above recursive lock ---------------
	global global_osthreadid_counter 
	global global_config_dictnum
	global global_thread_list 
	global global_deletion_list
	global global_parallel_execution_list
	global global_c
	global global_fatal_error 
	global global_talk_pair
	global global_write_to_msg_buffer
	#--------------------------------------------------------------------------

	global global_message_display_lock
	global global_get_input_lock
	global global_make_a_new_thread_lock
	global global_line_continuation_character

	# scope in each thread
	# what to do with threading 
	global_osthread_lock.acquire()
	config_dict_list=get_config_dict(namespace)
	mloc=threading.local()
	make_locals(config_dict_list[config_dictnum],mloc)
	#inspect.currentframe().f_globals.update(config_dict)
	# threading.local._local__impl.update(config_dict)
	# experimentation:  threading.local().__dict__.update(config_dict)
	td=get_temp_directory(mloc.assistant_name, osthreadid)
	global_thread_list[osthreadid][ThreadArray.TD]=td
	global_osthread_lock.release()

	ThreadLogger.add(osthreadid,td,f"{mloc.echo_output_file}.thread.{osthreadid}.log.txt")

	# no prints before here write to console
	print(f"assistant_name='{mloc.assistant_name}'")
	print(f'''Based on assistant_name the following directory 
will be used to store session files: {td}''')

	assistant_file_id, file_id_list = open_assistant(namespace, 
			client, 
			mloc.assistant_name, 
			mloc.purpose, 
			file_list=mloc.files, 
			tools=mloc.tools,
			osthreadid=osthreadid)
		
	print(f"Assistant: {assistant_file_id}")
	if file_id_list!=[]:
		print("With File ids:")
		for i,f in enumerate(file_id_list):
			print(f"{i}:\t{f}")
	else:
		print("With no uploaded files.")
	
	print("Commencing Run")
	
	first=1
	last=0
	messages=[]
	message_parser=create_parser()
	sandbox_files_id_set=set() # the {} can not be used to initialize the empty set. https://stackoverflow.com/questions/17663299/creating-an-empty-set

	thread[osthreadid] = client.beta.threads.create()

	while True:

		msg, parallel, cross_talk_bool, skip_command_processing=loop_construct(osthreadid, config_dictnum)

		msg=msg.strip(" \t\r\n")

		if msg=="": 
			continue	

		# listen to messages for file creation and id's
		sandbox_file_paired_with_sandbox_name_list, sandbox_files_id_set = scan_messages_for_sandbox_files(
				osthreadid,
				client, 
				thread[osthreadid], 
				messages, 
				sandbox_files_id_set) # passed by reference changes 

		#print("==========================================")
		#print(sandbox_files_id_set)
		#print(sandbox_file_paired_with_sandbox_name_list)
		#print("==========================================")

		if cross_talk_bool and len(msg)>=1 and msg[0]=="+":
			print(f"(A:{config_dictnum} Thread {osthreadid}) in cross talk mode no '+' commands.")
			msg=""

		if parallel and len(msg)>=1 and msg[0]=="+":
			print(f"(A:{config_dictnum} Thread {osthreadid}) in parallel mode no '+' commands.")
			msg=""

		if not skip_command_processing:
			if len(msg)>=1 and msg[0]=='+':
				# TODO logic for parallel execution here
				#	 preclude some + commands not all
				try:
					v=message_parser.parse_args(shlex.split(msg[1:], posix=True))
				except:
					continue
	
				if ("quitx" in v) and v.quitx==True:
					#if first==1:
					#	break  # nothing to clean up
	
					first=0 # suppress msg_preamble
					last=1
					msg=mloc.final_message
					if msg.strip(" \t\r\n")!="":
						print(f"Final message sent: '{msg}'")
					else:
						break
				elif ("rawx" in v) and v.rawx==True:
					raw_list(client, thread[osthreadid], messages)
					continue
				elif ("listx" in v) and v.listx==True:
					print(f"Sandbox files for A:{config_dictnum} Thread {osthreadid}:")
					for i,file in enumerate(sandbox_file_paired_with_sandbox_name_list):
						print(f"{i}\t\t{file[0]}\t\t{os.path.split(file[1])[-1]}")
					continue
				elif ("list_allx" in v) and v.list_allx==True:
					global_osthread_lock.acquire()
					for ii,val in enumerate(global_thread_list):
						print(f"Sandbox files for A:{val[ThreadArray.DICTNUM]} Thread {ii}:")
						for iii,file in enumerate(val[ThreadArray.SANDBOX_FILE_ID_LIST]):
							print(f"{iii}\t\t{file[0]}\t\t{os.path.split(file[1])[-1]}")
					global_osthread_lock.release()
					continue
				elif ("delete_localx" in v) and v.delete_localx==True:
					cwd = os.getcwd()
					td_full = os.path.join(cwd,td)
					onlyfiles = [os.path.join(td_full, f) for f in os.listdir(td_full) 
							if os.path.isfile(os.path.join(td_full, f))]
					if onlyfiles==[]:
						print("No files.")
						continue
					for i,f in enumerate(onlyfiles):
						try:
							if f[-len(".log.txt"):]!=".log.txt":
								os.unlink(f)
						except:
							print(f"{i}:\t{os.path.split(f)[-1]} error deleting file")
						else:
							print(f"{i}:\t{os.path.split(f)[-1]} deleted")
					continue
				elif ("list_localx" in v) and v.list_localx==True:
					cwd = os.getcwd()
					td_full = os.path.join(cwd,td)
					onlyfiles = [os.path.join(td_full, f) for f in os.listdir(td_full) 
							if os.path.isfile(os.path.join(td_full, f))]
					if onlyfiles==[]:
						print("No files.")
						continue
					for i,f in enumerate(onlyfiles):
						print(f"{i}:\t{os.path.split(f)[-1]}")
					continue
				elif ("get_allx" in v) and v.get_allx==True:
					for ii, val in enumerate(global_thread_list):
						if val[ThreadArray.SANDBOX_FILE_ID_LIST]==[]:
							print("No files to write. A:{val[ThreadArray.DICTNUM]} Thread {ii}.")
							continue
						
						print(f"Writing to directory: '{val[ThreadArray.TD]}'")
						sbfis=set(map(lambda x: x[0], val[ThreadArray.SANDBOX_FILE_ID_LIST])).copy()

						for i,file in enumerate(val[ThreadArray.SANDBOX_FILE_ID_LIST]):
							get_sandbox_remote_file(client,i,file,val[ThreadArray.TD], sbfis) 
					continue
				elif ("get_localx" in v) and v.get_localx==True:
					if sandbox_file_paired_with_sandbox_name_list==[]:
						print("No files to write.")
						continue
					
					print(f"Writing to directory: '{td}'")
	
					for i,file in enumerate(sandbox_file_paired_with_sandbox_name_list):
						get_sandbox_remote_file(client,i,file,td,
								sandbox_files_id_set) # of course passed by reference
					continue
				elif ("new_threadx" in v) and v.new_threadx==True:				
					global_osthread_lock.acquire()
					# lock the thread that created the new thread and
					#	start the new thread
					if not ("config" in v):
						global_config_dictnum=0
					elif v.config==None:
						global_config_dictnum=0
					elif v.config >=0 and v.config < len(config_dict_list):
						global_config_dictnum=v.config
					else:
						print(f"{v.config} out of range. Must be between 0 and {len(config_dict_list)-1} inclusive.")
						global_config_dictnum=0
						global_osthread_lock.release()
						continue
					global_thread_list[osthreadid][ThreadArray.LOCK].acquire()	
					global_osthread_lock.release()
	
					global_make_a_new_thread_lock.release()
	
					continue	
				elif ("list_threadx" in v) and v.list_threadx==True:				
					global_osthread_lock.acquire()
					integrity_check()
					try:
						for j in global_thread_list:
							if j[ThreadArray.BOOL_DELETED]==False:
								if j[ThreadArray.ID]!=osthreadid:
									if j[ThreadArray.READABLE_NAME]:
										print(f"A={j[ThreadArray.DICTNUM]} id={j[ThreadArray.ID]}\tAvailable\t\t\tname='{j[ThreadArray.READABLE_NAME]}'")
									else:
										print(f"A={j[ThreadArray.DICTNUM]} id={j[ThreadArray.ID]}\tAvailable")
	
								else:
									if j[ThreadArray.READABLE_NAME]:
										print(f"A={j[ThreadArray.DICTNUM]} id={j[ThreadArray.ID]}\t*** Active Thread ***\t\tname='{j[ThreadArray.READABLE_NAME]}'")
									else:
										print(f"A={j[ThreadArray.DICTNUM]} id={j[ThreadArray.ID]}\t*** Active Thread ***")
	
							else:
								if j[ThreadArray.READABLE_NAME]:
									print(f"A={j[ThreadArray.DICTNUM]} id={j[ThreadArray.ID]}\tDeleted -- exited status {j[ThreadArray.BOOL_EXITED]}\tname='{j[ThreadArray.READABLE_NAME]}'")
								else:
									print(f"A={j[ThreadArray.DICTNUM]} id={j[ThreadArray.ID]}\tDeleted -- exited status {j[ThreadArray.BOOL_EXITED]}")
	
	
						global_osthread_lock.release()
						continue
					except:
						print("global_thread_list corrupted Error. Exiting")
						global_osthread_lock.release()
						# TODO sys.exit() doesn't work for multiple threads
						sys.exit()
	
					global_osthread_lock.release()
					continue			
				elif ("quit_allx" in v) and v.quit_allx==True:				
					global_osthread_lock.acquire()
					integrity_check()
	
					thread_numbers=[]
					for j in global_thread_list:
						if j[ThreadArray.BOOL_DELETED]==False:
							if j[ThreadArray.ID]!=osthreadid:
								thread_numbers.append(j[ThreadArray.ID])
	
					global_deletion_list=[osthreadid]+thread_numbers 
	
					for j in thread_numbers: 
						global_thread_list[j][ThreadArray.BOOL_DELETED]=True 
						if j!=osthreadid: # osthreadid is already released
							global_thread_list[j][ThreadArray.LOCK].release()
			
					global_osthread_lock.release()
	
					# now exit thread we are on
					first=0 # suppress msg_preamble
					last=1
					msg=mloc.final_message.strip(" \t\r\n")
					if msg!="":
						print(f"Final message sent: '{msg}'")
					else:
						break
				elif ("new_asstx" in v) and v.new_asstx==True:				
					print(f"not yet implemented.")
					continue
					# TODO implement
					new_asst(namespace,v)
				elif ("name_threadx" in v) and v.name_threadx==True:				
					integrity_check()
					#name=concatenate_list(v.thread_name)
					if len(v.thread_name)!=1:
						print(f"one argument to thread_name only.")
						continue
	
					global_osthread_lock.acquire()
					global_thread_list[osthreadid][ThreadArray.READABLE_NAME]=v.thread_name[0] #name
					global_osthread_lock.release()
	
					continue
				elif ("join2_threadx" in v) and v.join2_threadx==True:				
					if v.thread_numbers==[] or v.thread_numbers==[osthreadid]:
						print(f"Must give two thread numbers. If one is given the thread you are on is assumed to be the talk pair")
						continue 
					elif len(v.thread_numbers) == 1:
						if not is_valid_thread(v.thread_numbers[0]):
							continue
						# thread is valid
						v.thread_numbers = [osthreadid]+v.thread_numbers
						pass
					elif len(v.thread_numbers) == 2:
						if not is_valid_thread(v.thread_numbers[0]) or not is_valid_thread(v.thread_numbers[1]):
							continue
					else:
						print(f"only 1 or 2 arguments allowed.")
						continue
					global_osthread_lock.acquire()

					if type(v.depth)==list:
						v.depth=v.depth[0]
					if type(v.seed)==list:
						v.seed=v.seed[0]

					global_talk_pair=[osthreadid]+v.thread_numbers+[v.depth, 0, v.seed, ""]

					thread_to_release_first=global_talk_pair[ThreadCrossTalk.THREAD1]
					thread_to_release_second=global_talk_pair[ThreadCrossTalk.THREAD2]

					if osthreadid != thread_to_release_first:
						global_thread_list[thread_to_release_first][ThreadArray.LOCK].release()
					else:
						pass # nothing to do osthreadid is first thread

					if osthreadid == thread_to_release_second:
						# wait until signaled by first thread
						global_thread_list[osthreadid][ThreadArray.LOCK].acquire()

					# if osthreadid is not part of the crosstalk then acquire the lock
					# release this when the conversation is done.
					if not osthreadid in v.thread_numbers:
						global_thread_list[osthreadid][ThreadArray.LOCK].acquire()

					global_osthread_lock.release()
					continue
				elif ("parallel_runx" in v) and v.parallel_runx==True:				
					global_osthread_lock.acquire()
					integrity_check()
					if v.thread_numbers==[] or v.thread_numbers==[osthreadid]:
						# parser should avoid this
						print("No threads slated for parallel execution. Error.")
						global_osthread_lock.release()
						continue
					try:
						# remove invalid thread numbers
						syntax_valid=True
						for j in v.thread_numbers:
							if not is_valid_thread(j):
								print(f"invalid thread number {j}.")
								syntax_valid=False
								break
		
						if not syntax_valid:
							global_osthread_lock.release()
							continue
		
						a=set(v.thread_numbers)
						a.discard(osthreadid)
						global_parallel_execution_list=[osthreadid]+list(a)
						# global_c=global_parallel_execution_list.copy()
						global_c=set()
		
						for j in global_parallel_execution_list: 
							if j==osthreadid:
								continue
							global_thread_list[j][ThreadArray.LOCK].release()
					except:
						print("Error in parallel_thread. Exiting") 
						global_osthread_lock.release()
						# TODO note sys.exit() doesn't work for multiple threads
						sys.exit()
					
					global_osthread_lock.release()
					continue # this thread now goes to get parallel input
				elif ("delete_threadx" in v) and v.delete_threadx==True:				
					global_osthread_lock.acquire()
					integrity_check()
					if v.thread_numbers==[]:
						# parser should avoid this
						print("No threads slated for deletion. Error.")
						global_osthread_lock.release()
						continue
					try:
						# remove invalid thread numbers
						syntax_valid=True
						for j in v.thread_numbers:
							if j==osthreadid:
								print(f"use '+ quit' to delete the thread ({j}) you are on -- or '+ quit_all' deletes all threads.")
								syntax_valid=False
								break
							elif not is_valid_thread(j): 
								print(f"invalid thread number {j}.")
								syntax_valid=False
								break
	
						if not syntax_valid:
							global_osthread_lock.release()
							continue
	
						global_deletion_list=[osthreadid]+v.thread_numbers 
	
						for j in v.thread_numbers: 
							global_thread_list[j][ThreadArray.BOOL_DELETED]=True 
							global_thread_list[j][ThreadArray.LOCK].release()
					except:
						print("Error in delete_thread.") 
						global_osthread_lock.release()
						# TODO sys.exit() doesn't work for multiple threads
						#sys.exit()
						continue
					
					global_osthread_lock.release()
					# wait until the threads are exited then proceed
					#   otherwise the input prompt will be hidden
					#   busy wait for now
					print(f"Waiting for thread(s) {v.thread_numbers} to exit...")
	
					global_osthread_lock.acquire()
					global_deletion_condition.wait_for(lambda : deletion_condition(v.thread_numbers))
					global_deletion_list=[]
					global_osthread_lock.release()
	
					continue
				elif ("switch_threadx" in v) and v.switch_threadx==True:				
					if not ("thread_number" in v):
						print("usage error.")
						continue
					thnum=v.thread_number 
					if thnum==osthreadid:
						print(f"Already on thread ({thnum}).")
						continue
	
					global_osthread_lock.acquire()
					try:
						if thnum<0 or thnum>=len(global_thread_list):
							print(f"Thread number ({thnum}) out of range")
							global_osthread_lock.release()
							continue
						if global_thread_list[thnum][ThreadArray.BOOL_DELETED]==True: # thread has been deleted
							print(f"Thread ({thnum}) deleted can't switch to it.")
							global_osthread_lock.release()
							continue
						if global_thread_list[thnum][ThreadArray.BOOL_DELETED]==False: # thread is active and can switch 
							# thnum != osthreadid
							global_thread_list[thnum][ThreadArray.LOCK].release()
							global_thread_list[osthreadid][ThreadArray.LOCK].acquire()
							global_osthread_lock.release()
						else:
							print("global_thread_list corrupted Error.")
							global_osthread_lock.release()
							# TODO note sys.exit() doesn't work here for multiple threads
							#sys.exit()
							continue
					except:
						print("Error or invalid thread")
						global_osthread_lock.release()
					continue
				else:
					print(f"Not a recognized command. Thread ({osthreadid})")
					#raw_list(client, thread[osthreadid], messages)
					continue
			
		# display information
		global_message_display_lock.acquire()

		if first==1:
			print(f"preamble: {mloc.msg_preamble}")
			msg = mloc.msg_preamble + "\n" + msg
			first=0

		print(f"full question/command to OpenAI GPT: {msg}")

		global_message_display_lock.release()

		if msg.strip(" \t\r\n")=="":
			print(f"(A:{config_dictnum} Thread {osthreadid}) empty not processing.")
			global_osthread_lock.acquire()
			if global_parallel_execution_list!=[]:
				global_osthread_lock.release()
				print(f"Did you issue a '+' command in parallel execution?")
				print(f"It will be ignored and passed as a null message and will not be processed.")
			else:
				global_osthread_lock.release()
		else:

			if cross_talk_bool:
				global_talk_pair[ThreadCrossTalk.MSG]=""
				global_write_to_msg_buffer=True
			
			# ok to run

			message = client.beta.threads.messages.create(
				thread_id=thread[osthreadid].id,
				role="user",
				content=msg,
			)
	
			run = client.beta.threads.runs.create(
				thread_id=thread[osthreadid].id,
				assistant_id=assistant_file_id,
			)
			
			run = wait_on_run(client, run, thread[osthreadid])
			
			messages = client.beta.threads.messages.list(thread_id=thread[osthreadid].id, order="asc", after=message.id)
	
			global_message_display_lock.acquire()
			flag=1
			for m in messages:
				flag=0
				display_message(client, m)
	
			if flag==1:
				print("\n------------------------------------\n")
				print("***Check token level--No messages***")
				print("\n------------------------------------\n")

			if cross_talk_bool:
				global_write_to_msg_buffer=False
		
			if last==1:
				print(f"Deleting OpenAI Thread '{thread[osthreadid].id}'")
				response = client.beta.threads.delete(thread[osthreadid].id)
				print(response)
				global_message_display_lock.release()
				break


			global_message_display_lock.release()

		# active thread activates the next one in cross talk
		if cross_talk_bool:
			global_osthread_lock.acquire()
			# release the lock of the other thread 
			tl=[first_thread,second_thread]=global_talk_pair[ThreadCrossTalk.THREAD1:ThreadCrossTalk.THREAD2+1]
			global_talk_pair[ThreadCrossTalk.CURRENT_DEPTH]+=1
			ctnum=global_talk_pair[ThreadCrossTalk.CURRENT_DEPTH]
			if ctnum>global_talk_pair[ThreadCrossTalk.MAX_DEPTH]:
				global_thread_list[tl[(ctnum+1)%2]][ThreadArray.LOCK].acquire() 
				global_thread_list[global_talk_pair[ThreadCrossTalk.THREAD_TO_RETURN_TO]][ThreadArray.LOCK].release()
				global_talk_pair=[]  # fix the join for the next iteration
			else:
				global_thread_list[tl[(ctnum+1)%2]][ThreadArray.LOCK].acquire() 
				global_thread_list[tl[(ctnum)%2]][ThreadArray.LOCK].release() 
			global_osthread_lock.release()
			pass
	
		# parallel_run 
		global_osthread_lock.acquire()
		if global_parallel_execution_list!=[]: # in parallel mode
			# the first thread that notices this can allow
			#	for input
			#   global_c is the set of active threads
			global_c.discard(osthreadid)

			if global_c==set():
				print(f"Status waiting for threads {{}} of {global_parallel_execution_list}...")
			else:
				print(f"Status waiting for threads {global_c} of {global_parallel_execution_list}...")

			# first was the thread that started the parallel execution
			#	return to it if all jobs are done
			#	global_c records which threads are done
			first=global_parallel_execution_list[0] 
			if len(global_c)==0: 
				global_parallel_execution_list=[]
				global_thread_list[first][ThreadArray.LOCK].release() #(***)# 
		global_osthread_lock.release()

	pass # end of Whileloop

	# update thread structure
	global_osthread_lock.acquire()
	global_thread_list[osthreadid][ThreadArray.BOOL_DELETED]=True
	global_osthread_lock.release()

	# to do add logic of active thread A
	# two ways to get here as of 12.23.2023
	#	thread A deletes this thread B through '+ delete_thread B C D'
	#		 ::: global_deletion_list==[A, B, C, D]
	#		 in which case A should stay active
	#	thread A quits directly  
	#		 ::: global_deletion_list==[]
	#		 in which case this should be executed
	#		 and the first non deleted or executed 
	#		 thread should become active
	# handle '+ quit'
	# can be reached through deletion as well
	if ("quit_allx" in v) and v.quit_allx==True:
		global_osthread_lock.acquire()
		print(f"Thread(s) {global_deletion_list} exiting/exited...")
		global_osthread_lock.release()
	elif ("quitx" in v) and v.quitx==True:
		global_osthread_lock.acquire()
		# if not None finding an active thread not in the process
		#	 of exiting to go to for the next input
		# if it is None exit
		index_active_thread=find_first_active_thread()
		if index_active_thread!=None:
			# race condition in the following if statement protected by
			#   global_osthread_lock.acquire() above
			#   note delete_thread unleashes all the deleted threads
			#   and the current thread doesn't know how it was '+ quit'
			#   if it was quit alone global_deletion_list==[]
			if global_deletion_list == []:  # current thread is quitting
				if global_thread_list[index_active_thread][ThreadArray.LOCK].locked():
					global_thread_list[index_active_thread][ThreadArray.LOCK].release() 
			else:
				# thread A is active in [A, B, C,...]
				#	A is waiting on a condition for B, C, etc.. to finish
				global_thread_list[osthreadid][ThreadArray.BOOL_EXITED]=True
				global_deletion_condition.notify()
				pass
		else:
			pass
		global_osthread_lock.release()

	ThreadLogger.close()

	# update thread structure
	global_osthread_lock.acquire()
	file_cleanup(client, sandbox_files_id_set)
	global_thread_list[osthreadid][ThreadArray.BOOL_EXITED]=True
	global_osthread_lock.release()

	return  #quits thread

if __name__=="__main__":
	parser = argparse.ArgumentParser(prog='openai-commandline.py',
					description='Provides some commandline fuctionality to openai API',
					epilog='commandline takes input to openai with + at the start of the \n command having additional functionality')

	valid_subparser_list=['delete','run']
	valid_with_help=valid_subparser_list[:] 
	valid_with_help.extend(['-h', '--help'])

	if len(sys.argv)==0:
		print("no arguments error")
		sys.exit()

	if len(sys.argv)==1:
		sys.argv.insert(1, "run")

	if sys.argv[1] not in valid_with_help:
		print("Assuming run command")
		sys.argv.insert(1, "run")

	print(f"Commandline={sys.argv}")

	subparsers = parser.add_subparsers(title='subcommands',
								   description='valid subcommands',
								   help='additional help',
								   required=False,
								   metavar=set(valid_subparser_list))

	parser_delete = subparsers.add_parser('delete', 
			help="deletes data on openai associated with the assistant")
	parser_delete.add_argument('-p', 
			action='store_true', 
			help='-p prompts for deletion of data file containing the ids')
	parser_delete.add_argument('-c', '--config', dest='c', nargs='+', metavar='configuration_file')
	parser_delete.set_defaults(func=dele)

	parser_null = subparsers.add_parser('run', help="runs the interactive openai program")
	parser_null.add_argument('-c', '--config', dest='c', nargs='+', metavar='configuration_file')
	parser_null.set_defaults(func=main)

	args = parser.parse_args()
	args.func(args)
	print("Done.")
