import copy
import random
from tqdm import tqdm
import numpy as np

__all__ = ['EvolutionFinder']


class ArchManager:
	def __init__(self):
		self.num_blocks = 20
		self.num_stages = 5
		self.kernel_sizes = [3, 5, 7]
		self.expand_ratios = [3, 4, 6]
		self.depths = [2, 3, 4]
		self.resolutions = [160, 176, 192, 208, 224]

	def random_sample(self):
		sample = {}
		d = []
		e = []
		ks = []
		for i in range(self.num_stages):
			d.append(random.choice(self.depths))

		for i in range(self.num_blocks):
			e.append(random.choice(self.expand_ratios))
			ks.append(random.choice(self.kernel_sizes))

		sample = {
			'wid': None,
			'ks': ks,
			'e': e,
			'd': d,
			'r': [random.choice(self.resolutions)]
		}

		return sample

	def random_resample(self, sample, i):
		assert i >= 0 and i < self.num_blocks
		sample['ks'][i] = random.choice(self.kernel_sizes)
		sample['e'][i] = random.choice(self.expand_ratios)

	def random_resample_depth(self, sample, i):
		assert i >= 0 and i < self.num_stages
		sample['d'][i] = random.choice(self.depths)

	def random_resample_resolution(self, sample):
		sample['r'][0] = random.choice(self.resolutions)


class EvolutionFinder:
	valid_constraint_range = {
		'flops': [150, 600],
		'note10': [15, 60],
	}

	def __init__(self, constraint_type, efficiency_constraint,
		     efficiency_predictor, accuracy_predictor, **kwargs):
		self.constraint_type = constraint_type
		if not constraint_type in self.valid_constraint_range.keys():
			self.invite_reset_constraint_type()
		if not isinstance(efficiency_constraint, tuple):
			efficiency_constraint = [efficiency_constraint]
		self.efficiency_constraint = efficiency_constraint
		#if not (efficiency_constraint <= self.valid_constraint_range[constraint_type][1] and
		#	efficiency_constraint >= self.valid_constraint_range[constraint_type][0]):
		#	self.invite_reset_constraint()

		self.efficiency_predictor = efficiency_predictor
		self.accuracy_predictor = accuracy_predictor
		self.arch_manager = ArchManager()
		self.num_blocks = self.arch_manager.num_blocks
		self.num_stages = self.arch_manager.num_stages

		self.mutate_prob = kwargs.get('mutate_prob', 0.1)
		self.population_size = kwargs.get('population_size', 100)
		self.max_time_budget = kwargs.get('max_time_budget', 500)
		self.max_time_budget2 = kwargs.get('max_time_budget2', 100)
		self.parent_ratio = kwargs.get('parent_ratio', 0.25)
		self.mutation_ratio = kwargs.get('mutation_ratio', 0.5)

	def invite_reset_constraint_type(self):
		print('Invalid constraint type! Please input one of:', list(self.valid_constraint_range.keys()))
		new_type = input()
		while new_type not in self.valid_constraint_range.keys():
			print('Invalid constraint type! Please input one of:', list(self.valid_constraint_range.keys()))
			new_type = input()
		self.constraint_type = new_type

	def invite_reset_constraint(self):
		print('Invalid constraint_value! Please input an integer in interval: [%d, %d]!' % (
			self.valid_constraint_range[self.constraint_type][0],
			self.valid_constraint_range[self.constraint_type][1])
		      )

		new_cons = input()
		while (not new_cons.isdigit()) or (int(new_cons) > self.valid_constraint_range[self.constraint_type][1]) or \
				(int(new_cons) < self.valid_constraint_range[self.constraint_type][0]):
			print('Invalid constraint_value! Please input an integer in interval: [%d, %d]!' % (
				self.valid_constraint_range[self.constraint_type][0],
				self.valid_constraint_range[self.constraint_type][1])
			      )
			new_cons = input()
		new_cons = int(new_cons)
		self.efficiency_constraint = new_cons

	def set_efficiency_constraint(self, new_constraint):
		self.efficiency_constraint = new_constraint

	def random_sample(self, whichone = 0):
		constraint = self.efficiency_constraint[whichone]
		while True:
			sample = self.arch_manager.random_sample()
			efficiency = self.efficiency_predictor.predict_efficiency(sample)
			if efficiency <= constraint:
				return sample, efficiency

	def mutate_sample(self, sample, whichone = 0):
		constraint = self.efficiency_constraint[whichone]
		while True:
			new_sample = copy.deepcopy(sample)

			if random.random() < self.mutate_prob:
				self.arch_manager.random_resample_resolution(new_sample)

			for i in range(self.num_blocks):
				if random.random() < self.mutate_prob:
					self.arch_manager.random_resample(new_sample, i)

			for i in range(self.num_stages):
				if random.random() < self.mutate_prob:
					self.arch_manager.random_resample_depth(new_sample, i)

			efficiency = self.efficiency_predictor.predict_efficiency(new_sample)
			if efficiency <= constraint:
				return new_sample, efficiency

	def crossover_sample(self, sample1, sample2, whichone = 0):
		constraint = self.efficiency_constraint[whichone]
		while True:
			new_sample = copy.deepcopy(sample1)
			for key in new_sample.keys():
				if not isinstance(new_sample[key], list):
					continue
				for i in range(len(new_sample[key])):
					new_sample[key][i] = random.choice([sample1[key][i], sample2[key][i]])

			efficiency = self.efficiency_predictor.predict_efficiency(new_sample)
			if efficiency <= constraint:
				return new_sample, efficiency

	def run_evolution_search(self, verbose=False):
		"""Run a single roll-out of regularized evolution to a fixed time budget."""
		max_time_budget = self.max_time_budget
		population_size = self.population_size
		mutation_numbers = int(round(self.mutation_ratio * population_size))
		parents_size = int(round(self.parent_ratio * population_size))
		constraint = self.efficiency_constraint

		best_valids = [-100]
		population = []  # (validation, sample, latency) tuples
		child_pool = []
		efficiency_pool = []
		best_info = None
		if verbose:
			print('Generate random population...')
		for _ in range(population_size):
			sample, efficiency = self.random_sample()
			child_pool.append(sample)
			efficiency_pool.append(efficiency)

		accs = self.accuracy_predictor.predict_accuracy(child_pool)
		for i in range(mutation_numbers):
			population.append((accs[i].item(), child_pool[i], efficiency_pool[i]))

		if verbose:
			print('Start Evolution...')
		# After the population is seeded, proceed with evolving the population.
		for iter in tqdm(range(max_time_budget), desc='Searching with %s constraint (%s)' % (self.constraint_type, self.efficiency_constraint)):
			parents = sorted(population, key=lambda x: x[0])[::-1][:parents_size]
			acc = parents[0][0]
			if verbose:
				print('Iter: {} Acc: {}'.format(iter - 1, parents[0][0]))

			if acc > best_valids[-1]:
				best_valids.append(acc)
				best_info = parents[0]
			else:
				best_valids.append(best_valids[-1])

			population = parents
			child_pool = []
			efficiency_pool = []

			for i in range(mutation_numbers):
				par_sample = population[np.random.randint(parents_size)][1]
				# Mutate
				new_sample, efficiency = self.mutate_sample(par_sample)
				child_pool.append(new_sample)
				efficiency_pool.append(efficiency)

			for i in range(population_size - mutation_numbers):
				par_sample1 = population[np.random.randint(parents_size)][1]
				par_sample2 = population[np.random.randint(parents_size)][1]
				# Crossover
				new_sample, efficiency = self.crossover_sample(par_sample1, par_sample2)
				child_pool.append(new_sample)
				efficiency_pool.append(efficiency)

			accs = self.accuracy_predictor.predict_accuracy(child_pool)
			for i in range(population_size):
				population.append((accs[i].item(), child_pool[i], efficiency_pool[i]))

		return best_valids, best_info

	def run_evolution_search_multi(self, verbose=False):
		"""
		CS 8803 OVER HERE!!!
		Bottom-up approach that runs the evolutionary search for multiple latency targets.
		"""
		max_time_budget = self.max_time_budget
		max_time_budget2 = self.max_time_budget2
		population_size = self.population_size
		mutation_numbers = int(round(self.mutation_ratio * population_size))
		parents_size = int(round(self.parent_ratio * population_size))
		constraint = self.efficiency_constraint[0]

		r_best_valids = {}
		r_best_info = {}

		best_valids = [-100]
		population = []  # (validation, sample, latency) tuples
		child_pool = []
		efficiency_pool = []
		best_info = None
		if verbose:
			print('Generate random population...')
		for _ in range(population_size):
			sample, efficiency = self.random_sample()
			child_pool.append(sample)
			efficiency_pool.append(efficiency)

		accs = self.accuracy_predictor.predict_accuracy(child_pool)
		for i in range(mutation_numbers):
			population.append((accs[i].item(), child_pool[i], efficiency_pool[i]))

		if verbose:
			print('Start Evolution...')
		# After the population is seeded, proceed with evolving the population.
		for iter in tqdm(range(max_time_budget), desc='Searching with %s constraint (%s)' % (self.constraint_type, self.efficiency_constraint[0])):
			parents = sorted(population, key=lambda x: x[0])[::-1][:parents_size]
			acc = parents[0][0]
			if verbose:
				print('Iter: {} Acc: {}'.format(iter - 1, parents[0][0]))

			if acc > best_valids[-1]:
				best_valids.append(acc)
				best_info = parents[0]
			else:
				best_valids.append(best_valids[-1])

			population = parents
			child_pool = []
			efficiency_pool = []

			for i in range(mutation_numbers):
				par_sample = population[np.random.randint(parents_size)][1]
				# Mutate
				new_sample, efficiency = self.mutate_sample(par_sample)
				child_pool.append(new_sample)
				efficiency_pool.append(efficiency)

			for i in range(population_size - mutation_numbers):
				par_sample1 = population[np.random.randint(parents_size)][1]
				par_sample2 = population[np.random.randint(parents_size)][1]
				# Crossover
				new_sample, efficiency = self.crossover_sample(par_sample1, par_sample2)
				child_pool.append(new_sample)
				efficiency_pool.append(efficiency)

			accs = self.accuracy_predictor.predict_accuracy(child_pool)
			for i in range(population_size):
				population.append((accs[i].item(), child_pool[i], efficiency_pool[i]))

		r_best_valids[0] =  best_valids
		r_best_info[0] = best_info

		k = 1
		while k < len(self.efficiency_constraint):
			constraint = self.efficiency_constraint[k]
			best_valids = [-100]
			best_info = None

			if verbose:
				print('Start Evolution...')
			# After the population is seeded, proceed with evolving the population.
			for iter in tqdm(range(max_time_budget2), desc='Searching with %s constraint (%s)' % (self.constraint_type, self.efficiency_constraint[k])):
				parents = sorted(population, key=lambda x: x[0])[::-1][:parents_size]
				acc = parents[0][0]
				if verbose:
					print('Iter: {} Acc: {}'.format(iter - 1, parents[0][0]))

				if acc > best_valids[-1]:
					best_valids.append(acc)
					best_info = parents[0]
				else:
					best_valids.append(best_valids[-1])

				population = parents
				child_pool = []
				efficiency_pool = []

				for i in range(mutation_numbers):
					par_sample = population[np.random.randint(parents_size)][1]
					# Mutate
					new_sample, efficiency = self.mutate_sample(par_sample, k)
					child_pool.append(new_sample)
					efficiency_pool.append(efficiency)

				for i in range(population_size - mutation_numbers):
					par_sample1 = population[np.random.randint(parents_size)][1]
					par_sample2 = population[np.random.randint(parents_size)][1]
					# Crossover
					new_sample, efficiency = self.crossover_sample(par_sample1, par_sample2, k)
					child_pool.append(new_sample)
					efficiency_pool.append(efficiency)

				accs = self.accuracy_predictor.predict_accuracy(child_pool)
				for i in range(population_size):
					population.append((accs[i].item(), child_pool[i], efficiency_pool[i]))

			r_best_valids[k] =  best_valids
			r_best_info[k] = best_info
			k += 1
		return r_best_valids, r_best_info

	def run_evolution_search_multi_pruning(self, verbose=False):
		max_time_budget = self.max_time_budget
		max_time_budget2 = self.max_time_budget2
		population_size = self.population_size
		mutation_numbers = int(round(self.mutation_ratio * population_size))
		parents_size = int(round(self.parent_ratio * population_size))
		constraint = self.efficiency_constraint[0]

		r_best_valids = {}
		r_best_info = {}

		best_valids = [-100]
		population = []  # (validation, sample, latency) tuples
		child_pool = []
		efficiency_pool = []
		best_info = None
		if verbose:
			print('Generate random population...')
		for _ in range(population_size):
			sample, efficiency = self.random_sample()
			child_pool.append(sample)
			efficiency_pool.append(efficiency)

		accs = self.accuracy_predictor.predict_accuracy(child_pool)
		for i in range(mutation_numbers):
			population.append((accs[i].item(), child_pool[i], efficiency_pool[i]))

		if verbose:
			print('Start Evolution...')
		# After the population is seeded, proceed with evolving the population.
		for iter in tqdm(range(max_time_budget), desc='Searching with %s constraint (%s)' % (self.constraint_type, self.efficiency_constraint[0])):
			parents = sorted(population, key=lambda x: x[0])[::-1][:parents_size]
			acc = parents[0][0]
			if verbose:
				print('Iter: {} Acc: {}'.format(iter - 1, parents[0][0]))

			if acc > best_valids[-1]:
				best_valids.append(acc)
				best_info = parents[0]
			else:
				best_valids.append(best_valids[-1])

			population = parents
			child_pool = []
			efficiency_pool = []

			for i in range(mutation_numbers):
				par_sample = population[np.random.randint(parents_size)][1]
				# Mutate
				new_sample, efficiency = self.mutate_sample(par_sample)
				child_pool.append(new_sample)
				efficiency_pool.append(efficiency)

			for i in range(population_size - mutation_numbers):
				par_sample1 = population[np.random.randint(parents_size)][1]
				par_sample2 = population[np.random.randint(parents_size)][1]
				# Crossover
				new_sample, efficiency = self.crossover_sample(par_sample1, par_sample2)
				child_pool.append(new_sample)
				efficiency_pool.append(efficiency)

			accs = self.accuracy_predictor.predict_accuracy(child_pool)
			for i in range(population_size):
				population.append((accs[i].item(), child_pool[i], efficiency_pool[i]))

		r_best_valids[0] =  best_valids
		r_best_info[0] = best_info

		k = 1
		while k < len(self.efficiency_constraint):
			constraint = self.efficiency_constraint[k]
			info = r_best_info[k-1][1]
			time = 9999999
			iter = 0
			idx = len(self.arch_manager.kernel_sizes)-2
			options = [1,2,3]
			i1 = 0
			i2 = 0
			i3 = 0
			idx1 = len(self.arch_manager.kernel_sizes)-2
			idx2 = len(self.arch_manager.depths)-2
			idx3 = len(self.arch_manager.expand_ratios)-2
			while time > constraint and len(options) > 0:
				choice = random.choice(options)
				if (choice == 1):
					if (i1 >= len(info['ks'])):
						i1 = 0
						idx1 -= 1
					if (idx1 < 0):
						options.remove(choice)
					else:
						chng = True
						while chng and i1 < len(info['ks']):
							if info['ks'][i1] > self.arch_manager.kernel_sizes[idx1]:
								info['ks'][i1] = self.arch_manager.kernel_sizes[idx1]
								time = self.efficiency_predictor.predict_efficiency(info)
								chng = False
							i1 += 1
				elif (choice == 2):
					if (i2 >= len(info['d'])):
						i2 = 0
						idx2 -= 1
					if (idx2 < 0):
						options.remove(choice)
					else:
						chng = True
						while chng and i2 < len(info['d']):
							if info['d'][i2] > self.arch_manager.depths[idx2]:
								info['d'][i2] = self.arch_manager.depths[idx2]
								time = self.efficiency_predictor.predict_efficiency(info)
								chng = False
							i2 += 1
				else:
					if (i3 >= len(info['e'])):
						i3 = 0
						idx3 -= 1
					if (idx3 < 0):
						options.remove(choice)
					else:
						chng = True
						while chng and i3 < len(info['e']):
							if info['e'][i3] > self.arch_manager.expand_ratios[idx3]:
								info['e'][i3] = self.arch_manager.expand_ratios[idx3]
								time = self.efficiency_predictor.predict_efficiency(info)
								chng = False
							i3 += 1
			time = self.efficiency_predictor.predict_efficiency(info)
			r_best_valids[k] =  self.accuracy_predictor.predict_accuracy([info])
			r_best_info[k] = [self.accuracy_predictor.predict_accuracy([info]),info,time]
			k += 1
		return r_best_valids, r_best_info

	def run_evolution_search_multi_mixed(self, verbose=False):
		"""
		CS 8803 OVER HERE!!!
		Top-down approach that runs the evolutionary search for multiple latency targets.
		"""
		max_time_budget = self.max_time_budget
		max_time_budget2 = self.max_time_budget2
		population_size = self.population_size
		mutation_numbers = int(round(self.mutation_ratio * population_size))
		parents_size = int(round(self.parent_ratio * population_size))
		constraint = self.efficiency_constraint[0]

		r_best_valids = {}
		r_best_info = {}

		best_valids = [-100]
		population = []  # (validation, sample, latency) tuples
		child_pool = []
		efficiency_pool = []
		best_info = None
		if verbose:
			print('Generate random population...')
		for _ in range(population_size):
			sample, efficiency = self.random_sample()
			child_pool.append(sample)
			efficiency_pool.append(efficiency)

		accs = self.accuracy_predictor.predict_accuracy(child_pool)
		for i in range(mutation_numbers):
			population.append((accs[i].item(), child_pool[i], efficiency_pool[i]))

		if verbose:
			print('Start Evolution...')
		# After the population is seeded, proceed with evolving the population.
		for iter in tqdm(range(max_time_budget), desc='Searching with %s constraint (%s)' % (self.constraint_type, self.efficiency_constraint[0])):
			parents = sorted(population, key=lambda x: x[0])[::-1][:parents_size]
			acc = parents[0][0]
			if verbose:
				print('Iter: {} Acc: {}'.format(iter - 1, parents[0][0]))

			if acc > best_valids[-1]:
				best_valids.append(acc)
				best_info = parents[0]
			else:
				best_valids.append(best_valids[-1])

			population = parents
			child_pool = []
			efficiency_pool = []

			for i in range(mutation_numbers):
				par_sample = population[np.random.randint(parents_size)][1]
				# Mutate
				new_sample, efficiency = self.mutate_sample(par_sample)
				child_pool.append(new_sample)
				efficiency_pool.append(efficiency)

			for i in range(population_size - mutation_numbers):
				par_sample1 = population[np.random.randint(parents_size)][1]
				par_sample2 = population[np.random.randint(parents_size)][1]
				# Crossover
				new_sample, efficiency = self.crossover_sample(par_sample1, par_sample2)
				child_pool.append(new_sample)
				efficiency_pool.append(efficiency)

			accs = self.accuracy_predictor.predict_accuracy(child_pool)
			for i in range(population_size):
				population.append((accs[i].item(), child_pool[i], efficiency_pool[i]))

		r_best_valids[0] =  best_valids
		r_best_info[0] = best_info

		k = 1
		while k < len(self.efficiency_constraint):
			constraint = self.efficiency_constraint[k]
			best_valids = [-100]
			best_info = None
			constraint = self.efficiency_constraint[k]
			info = r_best_info[k-1][1]
			time = 9999999
			iter = 0
			idx = len(self.arch_manager.kernel_sizes)-2
			options = [1,2,3]
			i1 = 0
			i2 = 0
			i3 = 0
			idx1 = len(self.arch_manager.kernel_sizes)-2
			idx2 = len(self.arch_manager.depths)-2
			idx3 = len(self.arch_manager.expand_ratios)-2
			while time > constraint and len(options) > 0:
				choice = random.choice(options)
				if (choice == 1):
					if (i1 >= len(info['ks'])):
						i1 = 0
						idx1 -= 1
					if (idx1 < 0):
						options.remove(choice)
					else:
						chng = True
						while chng and i1 < len(info['ks']):
							if info['ks'][i1] > self.arch_manager.kernel_sizes[idx1]:
								info['ks'][i1] = self.arch_manager.kernel_sizes[idx1]
								time = self.efficiency_predictor.predict_efficiency(info)
								chng = False
							i1 += 1
				elif (choice == 2):
					if (i2 >= len(info['d'])):
						i2 = 0
						idx2 -= 1
					if (idx2 < 0):
						options.remove(choice)
					else:
						chng = True
						while chng and i2 < len(info['d']):
							if info['d'][i2] > self.arch_manager.depths[idx2]:
								info['d'][i2] = self.arch_manager.depths[idx2]
								time = self.efficiency_predictor.predict_efficiency(info)
								chng = False
							i2 += 1
				else:
					if (i3 >= len(info['e'])):
						i3 = 0
						idx3 -= 1
					if (idx3 < 0):
						options.remove(choice)
					else:
						chng = True
						while chng and i3 < len(info['e']):
							if info['e'][i3] > self.arch_manager.expand_ratios[idx3]:
								info['e'][i3] = self.arch_manager.expand_ratios[idx3]
								time = self.efficiency_predictor.predict_efficiency(info)
								chng = False
							i3 += 1
			time = self.efficiency_predictor.predict_efficiency(info)
			acc = self.accuracy_predictor.predict_accuracy([info])
			best_valids = [-100]
			population = []
			child_pool = []
			efficiency_pool = []
			best_info = info
			for _ in range(population_size):
				child_pool.append(info)
				efficiency_pool.append(time)

			for i in range(mutation_numbers):
				population.append((acc,info,time))

			if verbose:
				print('Start Evolution...')
			# After the population is seeded, proceed with evolving the population.
			for iter in tqdm(range(max_time_budget2), desc='Searching with %s constraint (%s)' % (self.constraint_type, self.efficiency_constraint[k])):
				parents = sorted(population, key=lambda x: x[0])[::-1][:parents_size]
				acc = parents[0][0]
				if verbose:
					print('Iter: {} Acc: {}'.format(iter - 1, parents[0][0]))

				if acc > best_valids[-1]:
					best_valids.append(acc)
					best_info = parents[0]
				else:
					best_valids.append(best_valids[-1])

				population = parents
				child_pool = []
				efficiency_pool = []

				for i in range(mutation_numbers):
					par_sample = population[np.random.randint(parents_size)][1]
					# Mutate
					new_sample, efficiency = self.mutate_sample(par_sample, k)
					child_pool.append(new_sample)
					efficiency_pool.append(efficiency)

				for i in range(population_size - mutation_numbers):
					par_sample1 = population[np.random.randint(parents_size)][1]
					par_sample2 = population[np.random.randint(parents_size)][1]
					# Crossover
					new_sample, efficiency = self.crossover_sample(par_sample1, par_sample2, k)
					child_pool.append(new_sample)
					efficiency_pool.append(efficiency)

				accs = self.accuracy_predictor.predict_accuracy(child_pool)
				for i in range(population_size):
					population.append((accs[i].item(), child_pool[i], efficiency_pool[i]))

			r_best_valids[k] =  best_valids
			r_best_info[k] = best_info
			k += 1
		return r_best_valids, r_best_info
