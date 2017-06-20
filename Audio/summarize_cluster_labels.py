#Third party packages
import numpy as np
import matplotlib.pyplot as plt
from scipy import signal
import pandas as pd
import timeit
import os

import mpld3

import calc_audio_features as audio_func

from SQL.load_rows import load_audio_data
from SQL import settings

from SQL.addrows import add_results, create_results_row
from SQL.load_rows import load_cluster_labels, load_a_cluster_label, load_intensity


def get_labels():
	#import the labelled start and stop times
	labels = pd.read_csv('/home/graham/Insight2017/YoutubeVids/IrelandTranscript.csv')
	t_start = labels['start'].tolist()
	t_stop = labels['stop'].tolist()
	t_type = labels['type'].tolist()

	return t_start, t_stop, t_type

def create_label_vecs(timevec, t_start, t_stop, t_type):
    T_times = np.zeros(timevec.shape).astype(int)
    S_times = np.zeros(timevec.shape).astype(int)

    for start, stop, typ in zip(t_start, t_stop, t_type):
        if typ == 'T':
            new_times = (timevec > start) & (timevec < stop)
            T_times = T_times + new_times
        elif typ == 'S':
            new_times = (timevec > start) & (timevec < stop)
            S_times = S_times + new_times
    T_times = T_times.astype(bool)
    S_times = S_times.astype(bool)
    return T_times, S_times	
   

def get_minute_labels(timevec):
	'''for a given time vector, return a list of markers and labels
	in mm:ss format (try to return at least 4 labels that span the full length)'''
	m_max = np.ceil(timevec[-1]/60)
	m_min = np.floor(timevec[0]/60)
	#some short videos need to be labelled in 30s increments
	if m_max < 6:
		if m_max < 3:
			s_step = 30.0
		else:
			s_step = 60.0
	else:
		s_step = 60.0*round((m_max-m_min)/6)

	s_values = np.arange(m_min*60.0, m_max*60.0, s_step)
	m_labels = np.floor(s_values/60).astype(int)
	s_labels = (s_values % 60).astype(int)
	mmss_labels = [('%d:%02d' % (m,s)) for m,s in zip(m_labels, s_labels)]
	return mmss_labels, s_values

def visualize_classification_vs_time_with_truth(times, clusters, teacher_times, student_times):

	start = 0
	stop = times[-1]
	plot_times = (times >= start) & (times <= stop)

	minute_labels, minute_values = get_minute_labels(times)

	fig = plt.figure(figsize = (20,6), dpi = 60)
	ax = plt.subplot(111) 
	ax.plot(times[plot_times], student_times[plot_times], '--k')
	ax.set_xticks(minute_values)
	l = ax.set_xticklabels(minute_labels, rotation = 45)

	return fig

def get_plottable_waveform(yt_id):

	signal_intensity_df = load_intensity(yt_id)

	waveform = signal_intensity_df.as_matrix()

	print(len(waveform))
	plt.plot(waveform)
	plt.show()

	return waveform	

def visualize_classification_vs_time(yt_id, times, clusters):

	start = 0
	stop = times[-1]
	plot_times = (times >= start) & (times <= stop)

	minute_labels, minute_values = get_minute_labels(times)

	waveform = get_plottable_waveform()

	fig = plt.figure(figsize = (20,6), dpi = 60)
	ax = plt.subplot(111) 
	ax.fill_between(times[plot_times],0, clusters[plot_times])
	ax.set_xticks(minute_values)
	ax.set_yticks([0,1])
	l = ax.set_xticklabels(minute_labels, rotation = 45, fontsize = 18	)
	l = ax.set_yticklabels(['A','B'], fontsize = 18)

	return fig

def visualize_classification_vs_time_html(times, clusters):

	start = 0
	stop = times[-1]
	plot_times = (times >= start) & (times <= stop)

	minute_labels, minute_values = get_minute_labels(times)

	fig = plt.figure(figsize = (8,2))
	ax = plt.subplot(111) 
	ax.fill_between(times[plot_times],0, clusters[plot_times])
	ax.set_xticks(minute_values)
	ax.set_yticks([0])
	l = ax.set_xticklabels(minute_labels, rotation = 90, fontsize = 14	)
	l = ax.set_yticklabels([''], fontsize = 18)

	# plt.fill_between(times[plot_times],0, clusters[plot_times])

	fig_html = mpld3.fig_to_html(fig)

	return fig_html	

def visualize_classification_clusters(clusters, features, teacher_times, student_times):

	#2D projection of feature space
	pca = PCA(n_components = 2)
	plot_features = pca.fit_transform(normalize(features, axis=0))

	student_class = clusters.astype(bool)
	teacher_class = np.logical_not(clusters)

	fontsize = 20
	titlesize = fontsize+4

	plt.figure(figsize = (16,8))
	plt.subplot(121)
	plt.plot(plot_features[teacher_times,0],
		plot_features[teacher_times,1],'.r')
	plt.plot(plot_features[student_times,0],
		plot_features[student_times,1], '.k')
	plt.xlabel('Audio Feature A', fontsize = fontsize)
	plt.ylabel('Audio Feature B', fontsize = fontsize)
	plt.title('Labelled Data', fontsize = titlesize)

	plt.subplot(122)
	plt.plot(plot_features[teacher_class,0],
		plot_features[teacher_class,1],'.r', label = 'Teacher')
	plt.plot(plot_features[student_class,0],
		plot_features[student_class,1], '.k', label = 'Student')
	plt.xlabel('Audio Feature A', fontsize = fontsize)
	plt.ylabel('Audio Feature B', fontsize = fontsize)
	plt.title('Unsupervised Clusters', fontsize = titlesize)

	plt.tight_layout()
	plt.show()

def add_time_feature(times, features):
	f = np.vstack((features.transpose(),times)).transpose()

	return f

def add_nearby_time_features(features, n_time_steps = 9 ):
	'''to smooth out some of the fast noise in the classes,
	add new features to each time bin which are scaled versions of
	nearby time bins... this is possibly similar to classifying
	each time point individually and later applying median filter

	n_time_steps is the total number points to include BOTH forward
	and backward in time, and should be an odd number'''

	n_times = features.shape[0]
	n_features = features.shape[1]
	expanded_features = np.zeros((n_times, 
				(n_time_steps)*n_features))

	n_steps = np.floor(n_time_steps/2)
	step_list = np.linspace(-n_steps, n_steps, n_time_steps).astype(int)

	sigma = 5	
	weight_list = np.exp(-1.0 * step_list*step_list / sigma**2)

	for i, step, weight in zip(range(n_time_steps), step_list, weight_list):
		shifted_features = np.roll(features, step, axis = 0)

		expanded_features[:,i*n_features:(i+1)*n_features] = weight*shifted_features

	return expanded_features

def get_jumps(A):

	#create shifted version of A
	B = np.roll(A,-1)

	start = np.roll(np.logical_and((np.not_equal(A,B)), B),1)
	stop = np.logical_and((np.not_equal(A,B)), A)
	return start, stop	


def smooth_cluster_predictions(cluster_labels, smooth_window = 5):

	cluster_labels_smoothed = signal.medfilt(cluster_labels, smooth_window)
	return cluster_labels_smoothed	

def set_teacher_cluster(cluster_labels):
	'''takes the cluster labels as integers (0 or 1, 
	corresponding to teacher / not-teacher) and ensures
	that: 0 = teacher
		  1 = not-teacher	 
	by assuming that teacher talks most!  '''

	if np.sum(cluster_labels) < 0.5:
		cluster_labels = np.logical_not(cluster_labels.astype(bool)).astype(int)

	return cluster_labels	

def analyse_cluster_performance(times, cluster_labels):
	
	metrics = {}

	# get the TTR (time bins are equal, so just need to sum)
	TTR = 1 - float(np.sum(cluster_labels)) / len(cluster_labels)
	metrics['teacher_talk_ratio'] = TTR

	cluster_starts, cluster_stops = get_jumps(cluster_labels)
	
	#find the start times and stop times for the non-teacher speaker
	start_times = times[cluster_starts]
	stop_times = times[cluster_stops]
	n_interactions = np.sum(cluster_starts)
	metrics['interaction_times'] = start_times

	interaction_lengths = stop_times - start_times
	metrics['number_of_interactions'] = n_interactions
	metrics['interaction_lengths'] = interaction_lengths

	metrics = get_interaction_distribution(interaction_lengths, metrics)
	
	return metrics

def get_interaction_distribution(interaction_lengths, metrics):

	cutoff = 3.0 #max length of interaction (seconds) to consider short
	n_short_interactions = np.sum(interaction_lengths < cutoff)
	metrics['n_short_interactions'] = n_short_interactions

	long_cutoff = 20.0
	n_long_interactions = np.sum(interaction_lengths > long_cutoff)
	metrics['n_long_interactions'] = n_long_interactions

	return metrics

def histogram_interactions(interaction_lengths):
	'''Look at the way the detected interactions are distributed'''
	plt.hist(interaction_lengths, bins = [0.5, 1, 1.5, 2, 3, 4, 5, 7, 9, 12, 15, 20, 25, 30, 35, 40])
	plt.title("Interaction Lengths")
	plt.xlabel("Time (s)")
	plt.ylabel("Occurrences")

	plt.show()

def find_questions(interaction_times, interaction_lengths):
	'''Try to find a period in the file that looks like questions'''

	period_length = 25

	#find reasonably length interactions
	short_interactions = (interaction_lengths < 3.0)

	#find the best cluster of them
	n = 1
	short_times = interaction_times[short_interactions]
	too_far = False
	while not too_far:
		shifted_times = np.roll(short_times,-n)
		time_differences = shifted_times[0:-n] - short_times[0:-n]
		long_enough = time_differences < period_length
		if not np.any(long_enough):
			too_far = True
		else:
			question_index = time_differences.argmin()
			question_period_time = short_times[question_index]
			question_period_length = time_differences[question_index]
			n = n+1

	if n == 1:
		question_index = time_differences.argmin()
		question_period_time = short_times[question_index]
		question_period_length = time_differences[question_index]

	#need the index in the actual time array, not the short time arrays
	time_idx = np.where(
		interaction_times == short_times[question_index])[0]

	question_start = int(question_period_time) - 5
	question_end = int(question_period_time) + int(question_period_length)	 + 2	

	question_indices = range(time_idx,time_idx+n)

	return question_start, question_end, question_indices

def find_longest_question(interaction_times, interaction_lengths):
	'''finds the longest period of time in which the confidence
	is high for student talking'''
	longest_question = interaction_times[interaction_lengths.argmax()]

	#return start and end times
	start = int(longest_question)-15
	stop = int(longest_question) + int(interaction_lengths[interaction_lengths.argmax()]) + 10
	index = interaction_lengths.argmax()

	return start, stop, index

def get_question_periods(metrics):

	question_start_a, question_stop_a, indices_a = find_questions(
		metrics['interaction_times'], 
		metrics['interaction_lengths'])
	question_start_b, question_stop_b, indices_b = find_questions(
		np.delete(metrics['interaction_times'], indices_a), 
		np.delete(metrics['interaction_lengths'], indices_a))
	question_start_c, question_stop_c, indices_c = find_questions(
		np.delete(metrics['interaction_times'], indices_a + indices_b ), 
		np.delete(metrics['interaction_lengths'], indices_a + indices_b ))					

	long_question_start_a, long_question_stop_a, index_a = find_longest_question(
		metrics['interaction_times'], metrics['interaction_lengths'])
	long_question_start_b, long_question_stop_b, index_b = find_longest_question(
		np.delete(metrics['interaction_times'], index_a),
		np.delete(metrics['interaction_lengths'], index_a))				

	metrics['question_start_a'] = question_start_a
	metrics['question_start_b'] = question_start_b
	metrics['question_start_c'] = question_start_c
	metrics['question_stop_a'] = question_stop_a
	metrics['question_stop_b'] = question_stop_b
	metrics['question_stop_c'] = question_stop_c
	metrics['long_question_start_a'] = long_question_start_a
	metrics['long_question_start_b'] = long_question_start_b
	metrics['long_question_stop_a'] = long_question_stop_a
	metrics['long_question_stop_b'] = long_question_stop_b

	return metrics

def find_nearest(array,value):
    idx = (np.abs(array-value)).argmin()
    return idx

def match_time_labels(dest_times, cluster_times, cluster_labels):
	'''takes the set of time points cluster_times, and the associated
	cluster labels cluster_labels, and returns the cluster labels for each
	time in the differently sampled time vector dest_times'''
	dest_labels = np.zeros(dest_times.shape)

	#fill in all of the times which are 
	for i, time in enumerate(dest_times):
		dest_labels[i] = cluster_labels[find_nearest(cluster_times, time)]

	return dest_labels

def plot_clustered_waveform(yt_id = 'y2OFsG6qkBs'):

	Fs, x = audio_func.load_waveform(yt_id)
	try:
		x = audio_func.get_mono(x)
	except TypeError:
		print('Audio not properly loaded, make sure that audio data is accessible!')
	t = audio_func.get_time_vec(Fs,x)
	start = 1
	stop = int(t[-1])

	Fs_us, x_us, time_us = audio_func.undersample(Fs, x,N=10000)

	#load cluster data
	cluster_df = load_cluster_labels(yt_id)
	cluster_times = cluster_df['time'].as_matrix()
	cluster_labels = cluster_df['cluster_label_raw'].as_matrix()

	#find the waveform times that match cluster labels
	teacher_times = cluster_times[np.logical_not(cluster_labels.astype(bool))]
	student_times = cluster_times[cluster_labels]

	#pick the times from t that match the times from cluster_times where
	cluster_labels_us = match_time_labels(time_us, cluster_times, cluster_labels)
	teacher_labels_us = cluster_labels_us.astype(bool)
	student_labels_us = np.logical_not(teacher_labels_us)

	#plot the waveform in a tractable way
	plot_start = start
	plot_stop = stop
	plot_times = (time_us >= plot_start) & (time_us <= plot_stop)

	minute_labels, minute_values = get_minute_labels(time_us[plot_times])

	x_filtered = audio_func.low_pass_filter(Fs_us, x_us, tau = 1, order=3)
	x_max = x_filtered.max()
	x_teacher = np.zeros(x_filtered.shape)
	x_student = np.zeros(x_filtered.shape)
	x_teacher[teacher_labels_us] = x_filtered[teacher_labels_us]
	x_student[student_labels_us] = x_filtered[student_labels_us]

	fig = plt.figure(figsize = (8,3))
	ax = plt.subplot(111) 
	plt.fill_between(time_us[plot_times],-x_teacher[plot_times]/x_max,x_teacher[plot_times]/x_max, facecolor='red')
	plt.fill_between(time_us[plot_times],-x_student[plot_times]/x_max,x_student[plot_times]/x_max, facecolor='black')
	plt.ylim([-1,1])
	plt.xlabel('time (s)', fontsize = 14)
	plt.ylabel('Amplitude', fontsize = 14)
	ax.set_xticks(minute_values)
	ax.set_yticks([0])
	l = ax.set_xticklabels(minute_labels, rotation = 45, fontsize = 14	)
	l = ax.set_yticklabels([''], fontsize = 14)
	plt.tight_layout()

	return fig

def plot_waveform(yt_id = 'y2OFsG6qkBs'):

	Fs, x = audio_func.load_waveform(yt_id)
	try:
		x = audio_func.get_mono(x)
	except TypeError:
		print('Audio not properly loaded, make sure that audio data is accessible!')
	t = audio_func.get_time_vec(Fs,x)
	start = 1
	stop = int(t[-1])

	Fs_us, x_us, time_us = audio_func.undersample(Fs, x,N=10000)

	#plot the waveform in a tractable way
	plot_start = start
	plot_stop = stop
	plot_times = (time_us >= plot_start) & (time_us <= plot_stop)

	minute_labels, minute_values = get_minute_labels(time_us[plot_times])

	x_filtered = audio_func.low_pass_filter(Fs_us, x_us, tau = 1, order=3)
	x_max = x_filtered.max()

	fig = plt.figure(figsize = (8,3))
	ax = plt.subplot(111) 
	plt.fill_between(time_us[plot_times],-x_filtered[plot_times]/x_max,x_filtered[plot_times]/x_max)
	plt.ylim([-1,1])
	plt.xlabel('time (s)', fontsize = 14)
	plt.ylabel('Amplitude', fontsize = 14)
	ax.set_xticks(minute_values)
	ax.set_yticks([0])
	l = ax.set_xticklabels(minute_labels, rotation = 45, fontsize = 14	)
	l = ax.set_yticklabels([''], fontsize = 14)
	plt.tight_layout()

	return fig	

def plot_clustered_waveform_html(yt_id = 'y2OFsG6qkBs'):

	Fs, x = audio_func.load_waveform(yt_id)
	try:
		x = audio_func.get_mono(x)
	except TypeError:
		print('Audio not properly loaded, make sure that audio data is accessible!')
	t = audio_func.get_time_vec(Fs,x)
	start = 1
	stop = int(t[-1])

	Fs_us, x_us, time_us = audio_func.undersample(Fs, x,N=10000)

	#load cluster data
	cluster_df = load_cluster_labels(yt_id)
	cluster_times = cluster_df['time'].as_matrix()
	cluster_labels = cluster_df['cluster_label_raw'].as_matrix()

	#find the waveform times that match cluster labels
	teacher_times = cluster_times[np.logical_not(cluster_labels.astype(bool))]
	student_times = cluster_times[cluster_labels]

	#pick the times from t that match the times from cluster_times where
	cluster_labels_us = match_time_labels(time_us, cluster_times, cluster_labels)
	teacher_labels_us = cluster_labels_us.astype(bool)
	student_labels_us = np.logical_not(teacher_labels_us)

	#plot the waveform in a tractable way
	plot_start = start
	plot_stop = stop
	plot_times = (time_us >= plot_start) & (time_us <= plot_stop)

	minute_labels, minute_values = get_minute_labels(time_us[plot_times])

	x_filtered = audio_func.low_pass_filter(Fs_us, x_us, tau = 1, order=3)
	x_max = x_filtered.max()
	x_teacher = np.zeros(x_filtered.shape)
	x_student = np.zeros(x_filtered.shape)
	x_teacher[teacher_labels_us] = x_filtered[teacher_labels_us]
	x_student[student_labels_us] = x_filtered[student_labels_us]

	fig = plt.figure(figsize = (8,2))
	ax = plt.subplot(111) 
	plt.fill_between(time_us[plot_times],-x_teacher[plot_times]/x_max,x_teacher[plot_times]/x_max, facecolor='red')
	plt.fill_between(time_us[plot_times],-x_student[plot_times]/x_max,x_student[plot_times]/x_max, facecolor='black')
	plt.xlabel('time (s)', fontsize = 14)
	plt.ylabel('Amplitude', fontsize = 14)
	ax.set_xticks(minute_values)
	ax.set_yticks([0])
	l = ax.set_xticklabels(minute_labels, rotation = 45, fontsize = 14	)
	l = ax.set_yticklabels([''], fontsize = 14)
	plt.tight_layout()

	fig_html = mpld3.fig_to_html(fig)

	return fig_html	

#---------
#Run here:
#---------

def summarize_video(yt_id = 'y2OFsG6qkBs'):

	cluster_df = load_cluster_labels(yt_id)

	times = cluster_df['time'].as_matrix()
	cluster_labels = cluster_df['cluster_label_raw'].as_matrix()

	cluster_labels = set_teacher_cluster(cluster_labels)

	metrics = analyse_cluster_performance(times, cluster_labels)
	metrics['video_length'] = times[-1]

	metrics = get_question_periods(metrics)

	#save all the metrics to the results table
	add_results(yt_id, metrics)

def plot_speaker_vs_time(yt_id):
	cluster_df = load_cluster_labels(yt_id)

	times = cluster_df['time'].as_matrix()
	cluster_labels = cluster_df['cluster_label_raw'].as_matrix()

	fig_html = visualize_classification_vs_time_html(times, cluster_labels)

	return fig_html

def plot_speaker_vs_time_test(yt_id):
	cluster_df = load_cluster_labels(yt_id)

	times = cluster_df['time'].as_matrix()
	cluster_labels = cluster_df['cluster_label_raw'].as_matrix()

	fig = visualize_classification_vs_time(yt_id, times, cluster_labels)

	return fig


if __name__ == '__main__':
	fig = plot_clustered_waveform('dqPjgQwoXLQ')
	plt.show()