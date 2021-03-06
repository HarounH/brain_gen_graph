"""
File to process ward agglomerative into a tree
"""

import os
import pickle
import numpy as np
import torch
import heapq
from collections import defaultdict, deque
import scipy.sparse as scsp
import torch.sparse as tsp
from data.new_agglo import (
    _hc_cut,
)


class WardNode():
    def __init__(self, val):
        self.val = val
        self.children = []
        self.parent = None
        self.exist = False

    def __lt__(self, other):
        if self.depth == other.depth:
            return self.val < other.val
        else:
            return self.depth > other.depth


class WardTree():
    """
        Takes in a ward tree object of class data.new_agglo.AgglomerativeClustering
    """
    def __init__(self, ward):
        # ward: str to pickle of AgglomerativeClustering or AgglomerativeClustering obj
        if isinstance(ward, str):
            with open(ward, "rb") as f:
                ward = pickle.load(f)
        self.ward = ward  # Dont need to store this.
        self.n_samples = ward.children_.shape[0] + 1

    def cut(self, cutsize):
        return _hc_cut(cutsize, self.ward.children_, self.ward.n_leaves_)  # Label positions according to cut of cutsize

    def get_leaves(self):
        return list(range(self.ward.n_leaves_))

    def get_level(self, level_size):
        # Similar to new_agglo._hc_cut, but we dont assign labels to the leaf nodes.
        children = self.ward.children_
        n_leaves = self.ward.n_leaves_
        # We maintain a PQ, using the negative of the node idx since heapq is a min-PQ
        level = [-max(children[-1]) - 1]
        for i in range(level_size - 1):
            new_children = children[- level[0] - n_leaves]
            heapq.heappush(level, -new_children[0])
            heapq.heappushpop(level, -new_children[1])
        return [-n for n in level]

    def get_adj(self, node, destination_nodes, children, n_leaves, dest=None):
        if dest is None:
            dest = {v: i for i, v in enumerate(destination_nodes)}
        # Get adjacency from node to dest
        adj = []
        # if node-> destination_nodes[idx] then append idx to adj_list[-1]...
        next_nodes = deque([node])
        l = 1  # length of next_nodes
        while l > 0:
            next_node = next_nodes.pop()
            l -= 1
            if next_node in dest:
                adj.append(dest[next_node])
            else:
                next_nodes.append(children[next_node - n_leaves][0])
                next_nodes.append(children[next_node - n_leaves][1])
                l += 2
        return adj

    def get_level_and_adjacency(self, level_size, destination_nodes, n_regions=32):
        """
            Finds a level of size level_size, and then returns an adjacency list from the new level to destination-nodes
            Returns:
                level_nodes: indices associated with nodes at new level
                regions: array containing region id of each level node
                adj_list: Adjacency list from level_nodes to destination_nodes... length = level_size
        """
        if (n_regions >= level_size):
            print("n_regions={} >= level_size={} is not allowed. setting n_regions < level_size".format(n_regions, level_size))
            n_regions = level_size - 1
        level_nodes = self.get_level(level_size)
        adj_list = []
        children = self.ward.children_
        n_leaves = self.ward.n_leaves_
        dest = {v: i for i, v in enumerate(destination_nodes)}
        for node in level_nodes:
            adj_list.append(self.get_adj(node, destination_nodes, children, n_leaves, dest=dest))

        region_nodes = self.get_level(n_regions)
        regions = np.zeros(level_size)
        level_dest = {v: i for i, v in enumerate(level_nodes)}
        for i, rnode in enumerate(region_nodes):
            regions[self.get_adj(rnode, level_nodes, children, n_leaves, dest=level_dest)] = i
        return level_nodes, regions, adj_list

    def get_parents(self, nodes):
        # Nodes: list-like
        children = self.ward.children_
        n_leaves = self.ward.n_leaves_
        parents = {k: None for k in nodes}
        for i in range(len(children)):
            for j in range(2):
                candidate = children[i][j]
                if candidate in parents:
                    parents[candidate] = i + n_leaves
        return [parents[k] for k in nodes]

    def get_self_adj(self, nodes, upward_hops=2):
        """
        Returns an adjacency by going up and coming back down.
        """
        ancestors = [[] for n in nodes]
        cur_nodes = nodes
        for i in range(upward_hops):
            for i in range(len(cur_nodes)):
                ancestors[i].append(cur_nodes[i])
            cur_nodes = self.get_parents(cur_nodes)
        # Ancestors is now ready. 2 nodes are connected if they share an ancestor
        ancestor2node_idx = defaultdict(lambda: [])
        for i in range(len(nodes)):
            for anc in ancestors[i]:
                ancestor2node_idx[anc].append(i)
        adj_list = [[] for n in nodes]
        for anc, nbr in ancestor2node_idx.items():
            for i in nbr:
                for j in nbr:
                    if j not in adj_list[i]:
                        adj_list[i].append(j)
        return adj_list


class WardTree_deprecated():
    def __init__(self, ward):
        # import pdb; pdb.set_trace()
        if isinstance(ward, str):
            with open(ward, "rb") as f:
                ward = pickle.load(f)
        self.ward = ward  # Dont need to store this.
        self.n_samples = ward.children_.shape[0] + 1
        self.node_idxs = list(range(2 * self.n_samples))
        self.nodes = {val: WardNode(val) for val in self.node_idxs}

        self.construct_tree()

    def construct_tree(self):
        for i in range(self.ward.children_.shape[0]):
            cidx0, cidx1 = self.ward.children_[i]
            pidx = self.n_samples + i
            assert(len(self.nodes[pidx].children) == 0)
            assert(self.nodes[cidx0].parent is None)
            assert(self.nodes[cidx1].parent is None)

            self.nodes[pidx].exist = True
            self.nodes[cidx0].exist = True
            self.nodes[cidx1].exist = True
            self.nodes[pidx].children.extend([self.nodes[cidx0], self.nodes[cidx1]])
            self.nodes[cidx0].parent = self.nodes[pidx]
            self.nodes[cidx1].parent = self.nodes[pidx]

        self.node_idxs = [k for k, val in self.nodes.items() if val.exist]
        self.nodes = {k: self.nodes[k] for k in self.node_idxs}

        self.roots = [val for k, val in self.nodes.items() if val.parent is None]
        # Write out depths
        level = [val for k, val in self.nodes.items() if val.parent is None]
        current_depth = 0
        while len(level) > 0:
            new_level = []
            for node in level:
                node.depth = current_depth
                new_level.extend(node.children)
            level = new_level
            current_depth += 1

    def get_leaves(self):
        # Linear search is okay - graph is linear in #nodes=#edges
        return [self.nodes[k] for k in self.node_idxs if (len(self.nodes[k].children) == 0)]

    def get_depth(self, d):
        # Linear search is okay really.
        return [self.nodes[k] for k in self.node_idxs if (self.nodes[k].depth == d)]

    def first_level_of_size(self, n):
        level = self.roots
        while len(level) < n:
            level = sum([x.children for x in level], [])
        return level

    def make_val2region(self, region_n):
        region_level = self.first_level_of_size(region_n)
        self.region2regionrootval = {}
        self.val2region = {}
        for ridx, rnode in enumerate(region_level):
            self.val2region[rnode.val] = ridx
            self.region2regionrootval[ridx] = rnode.val
            level = rnode.children
            rnode.ridx = ridx
            while len(level) > 0:
                new_level = []
                for node in level:
                    self.val2region[node.val] = ridx
                    node.ridx = ridx
                    new_level.extend(node.children)
                level = new_level
        return self.val2region

    def region_faithful_go_up_to_reduce(self, from_nodes, level_size, degree_normalized=True):
        # from_nodes (WardNode list)
        # Goes up from from_nodes in a breadth first fashion until to_nodes is reached
        base_val_to_idx = {node.val: i for i, node in enumerate(from_nodes)}

        # INVAR 0: Everything that is in the level,
        #   has adjacencies to the base stored in the variable adjacencies2base
        adjacencies2base = {node.val: [node.val] for node in from_nodes}

        # nodes_pq is the level that will be output once its cut down to the right size.
        # INVAR 1: nodes_pq[i] is at least as deep as nodes_pq[i+1]
        nodes_pq = [nd for nd in from_nodes]
        heapq.heapify(nodes_pq)  # Ensuring INVAR 1
        while(len(nodes_pq) > level_size):
            old_node = heapq.heappop(nodes_pq)
            # We look at old_nodes parent.
            new_node = old_node.parent
            if new_node is not None:
                # print("popped {} to get {}".format(old_node.val, new_node.val))
                # 2 cases - either its in the level or its not.
                # if its in the level, then we should just modify its adjacencies
                if new_node.val in adjacencies2base.keys():
                    adjacencies2base[new_node.val].extend(adjacencies2base[old_node.val])
                else:  # Replacing old node by new_node essentially.
                    heapq.heappush(nodes_pq, new_node)
                    adjacencies2base[new_node.val] = adjacencies2base[old_node.val]

                # base case: old_node was in the original base level.
                if old_node.val in base_val_to_idx:
                    adjacencies2base[new_node.val].append(old_node.val)
                adjacencies2base[new_node.val] = list(set(adjacencies2base[new_node.val]))
                del adjacencies2base[old_node.val]  # old_node is no longer in the level
            else:
                continue

        # unique_regions is an abused variable. just trust it.
        unique_regions = {-1: False}  # False since it isnt technically a region.
        for node in from_nodes:
            ridx = self.val2region[node.val]
            unique_regions[ridx] = True
        for node in nodes_pq:
            ridx = self.val2region[node.val]
            unique_regions[ridx] = True

        out_nodes = nodes_pq
        in_nodes = from_nodes
        dict_data = {k: [] for k, _ in unique_regions.items()}
        dict_rows = {k: [] for k, _ in unique_regions.items()}
        dict_cols = {k: [] for k, _ in unique_regions.items()}
        dict_adj_lists = {k: [] for k, _ in unique_regions.items()}
        dict_adj_matrices = {k: None for k, _ in unique_regions.items()}

        for out_idx, out_node in enumerate(out_nodes):
            # It goes into two places - the region and the -1.
            region_idx = self.val2region[out_node.val]
            unique_regions[region_idx] = False
            for k, _ in unique_regions.items():
                dict_adj_lists[k].append([])

            for adj_node_val in adjacencies2base[out_node.val]:
                in_idx = base_val_to_idx[adj_node_val]
                dict_adj_lists[-1][-1].append(in_idx)
                dict_data[-1].append(1.0 / len(adjacencies2base[out_node.val]) if degree_normalized else 1.0)
                dict_rows[-1].append(out_idx)
                dict_cols[-1].append(in_idx)

                dict_adj_lists[region_idx][-1].append(in_idx)
                dict_data[region_idx].append(1.0 / len(adjacencies2base[out_node.val]) if degree_normalized else 1.0)
                dict_rows[region_idx].append(out_idx)
                dict_cols[region_idx].append(in_idx)

        for k, _ in unique_regions.items():
            dict_adj_matrices[k] = scsp.coo_matrix((dict_data[k], (dict_rows[k], dict_cols[k])), shape=(len(out_nodes), len(in_nodes)))
        assert(all(not(v) for k, v in unique_regions.items()))
        return out_nodes, dict_adj_matrices, dict_adj_lists


def get_adjacency_list(nodes_from, nodes_to):
    # adjacency list is from position in nodes_from to position in nodes_to
    to_vals = [node.val for node in nodes_to]
    adj_list = []
    for start_node in nodes_from:
        adjacency = []
        stack = [start_node]
        while len(stack) > 0:
            next_node = stack.pop()
            try:
                to_idx = to_vals.index(next_node.val)
                adjacency.append(to_idx)
            except ValueError:
                pass
            stack.extend(next_node.children)
        adj_list.append(adjacency)
    return adj_list


def go_up_to_reduce(from_nodes, level_size, degree_normalized=True):
    # from_nodes (WardNode list)
    # Goes up from from_nodes in a breadth first fashion
    base_val_to_idx = {node.val: i for i, node in enumerate(from_nodes)}

    # INVAR 0: Everything that is in the level,
    #   has adjacencies to the base stored in the variable adjacencies2base
    adjacencies2base = {node.val: [node.val] for node in from_nodes}

    # nodes_pq is the level that will be output once its cut down to the right size.
    # INVAR 1: nodes_pq[i] is at least as deep as nodes_pq[i+1]
    nodes_pq = [nd for nd in from_nodes]
    heapq.heapify(nodes_pq)  # Ensuring INVAR 1
    while(len(nodes_pq) > level_size):
        old_node = heapq.heappop(nodes_pq)
        # We look at old_nodes parent.
        new_node = old_node.parent
        if new_node is not None:
            # print("popped {} to get {}".format(old_node.val, new_node.val))
            # 2 cases - either its in the level or its not.
            # if its in the level, then we should just modify its adjacencies
            if new_node.val in adjacencies2base.keys():
                adjacencies2base[new_node.val].extend(adjacencies2base[old_node.val])
            else:  # Replacing old node by new_node essentially.
                heapq.heappush(nodes_pq, new_node)
                adjacencies2base[new_node.val] = adjacencies2base[old_node.val]

            # base case: old_node was in the original base level.
            if old_node.val in base_val_to_idx:
                adjacencies2base[new_node.val].append(old_node.val)
            adjacencies2base[new_node.val] = list(set(adjacencies2base[new_node.val]))
            del adjacencies2base[old_node.val]  # old_node is no longer in the level
        else:
            continue
    out_nodes = nodes_pq
    in_nodes = from_nodes
    data = []
    rows = []
    cols = []
    adj_list = []  #
    for ridx, out_node in enumerate(out_nodes):
        adj_list.append([])
        for adj_node_val in adjacencies2base[out_node.val]:
            cidx = base_val_to_idx[adj_node_val]
            adj_list[-1].append(cidx)
            data.append(1.0 / len(adjacencies2base[out_node.val]) if degree_normalized else 1.0)
            rows.append(ridx)
            cols.append(cidx)
    adj_matrix = scsp.coo_matrix((data, (rows, cols)), shape=(len(out_nodes), len(in_nodes)))
    return out_nodes, adj_matrix, adj_list
