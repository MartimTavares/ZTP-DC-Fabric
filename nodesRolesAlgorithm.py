import numpy as np

def intersect(lst1, lst2):
    #convert to list in case it is a single element int
    if type(lst1) == int:
        lst1 = [lst1]
    if type(lst2) == int:
        lst2 = [lst2]
    intersection = []
    if len(lst1) <= len(lst2):
        for e in range(len(lst1)):
            if lst1[e] in lst2:
                intersection.append(lst1[e])
    else:
        for e in range(len(lst2)):
            if lst2[e] in lst1:
                intersection.append(lst2[e])
    return intersection

def shortestPath(Costs,Source,Destination):
  
    numNodes=Costs.shape[0] #Number of nodes
  
    NodeLabels=Costs[Source,:] #Vector of node label
  
    TempNodes = np.arange(0, numNodes) #Vector of temporary nodes
    TempNodes = np.delete(TempNodes, Source) #Remove source node from vector of temporary nodes
    TempLabels = NodeLabels.copy() #Vector of temporary labels
    TempLabels = np.delete(TempLabels, Source) #Remove label of source node from vector of temporary labels
  
    NodeParents = np.full(numNodes, Source) #Vector of node parents
    
    p=Source #Node that becomes permanently labelled

    while (True):
        i = np.argmin(TempLabels) #Determines index of lower label node
        cost = np.min(TempLabels) #Determines label of lower label node
        p=TempNodes[i] #p is the next permanent node
        TempNodes = np.delete(TempNodes, i) #Remove p node from vector of temporary nodes
        TempLabels = np.delete(TempLabels, i) #Remove label of p node from vector of temporary labels
        NodeLabels[p]=cost #Update node label of p node
        if p == Destination: 
           break #Iteration ends when destination found
        for k in range(len(TempNodes)): #Update labels of temporary nodes
            nt = TempNodes[k] #Next temporary node
            ct = NodeLabels[p] + Costs[p,nt] #Calculate cost to temporary node via p
            if ct < NodeLabels[nt]: #Update only if new cost is lower
                TempLabels[k]=ct #Update label on vector of temporary node labels
                NodeLabels[nt]=ct #Update label on vector of node labels
                NodeParents[nt]=p #Update node parent
  
    #Determines route from vector of node parents  
    Route=[Destination]
    r = Destination
    while (r != Source):
        r = NodeParents[r]
        Route.insert(0, r)

    return Route, cost


def nodesRolesAlgorithm(g):

    numNodes = len(g)

    ## - Determines incidence matrix; will be used to compute the shortest paths
    R = np.zeros((numNodes, numNodes))
    for i in range(numNodes):
        for j in range(len(g[i])):
            if g[i] != [0]:
                index = g[i][j]#-1
                R[i][index] = 1

    ## - Determines the groups of nodes that share exactly the same neighbors
    #eqgroups is a list of lists, where the 1st level list represents a group; a
    #group is a list of 2 vectors, the 1st with the nodes and the 2nd with the
    #common neighbors
    eqgroups=[[[],[]]]

    for node in range(0, numNodes):
        nei1=g[node] #reads neighbors of i-th node
        nei1seen=0 #no group with nei1 neighbors seen in eqgroups
        for j in range(0, len(eqgroups)): #scans the already formed groups
            nei2=eqgroups[j][1] #reads neighbors of j-th group
            if set(nei1) == set(nei2): #a group with nei1 neighbors already in eqgroups
                nei1seen = 1 #flag indicating nei1 neighbors found eqgroups
                eqgroups[j][0].append(node) #add nodes nodes to this group
        if nei1seen == 0: #no group found with nei1 neighbors
            eqgroups.append([[node],nei1]) #add new element to eqgroups including node ath its neighbors

    ## - Determines pairs of groups at a shortest distance of 4 hops; these groups are
    #leaves and border leaves of different PODs; this is only possible due to the
    #imposed topological restrictions; if they were not taken there will other pairs
    #of groups at a distance of 4
    #leave4_pairs is a list with 2 levels where level 1 is a pair of groups and
    #level 2 is a group from the pair; a group is a list of 2 vectors, where the
    #first vector include nodes and the second vector the corresponding neighbors.
    costs=R
    costs[R == 0] = np.inf
    leaves4pairs=[[],[]]
    leaves1pairs=[[],[]]
    all_hop_count = []

    for i in range(1,len(eqgroups)-1): 
        for j in range(i+1,len(eqgroups)):
            o = eqgroups[i][0][0]
            d = eqgroups[j][0][0]
            a, hop_count = shortestPath(costs,o,d)
            if hop_count != np.inf:
                all_hop_count.append(hop_count)
            if hop_count == 4:
                leaves4pairs.append([eqgroups[i], eqgroups[j]])
            elif hop_count == 1:
                leaves1pairs.append([eqgroups[i], eqgroups[j]])

    #Remove empty lists (due to row and column 0) from leaves4pairs
    index_remove = []
    for e in range(len(leaves4pairs)):
        if leaves4pairs[e] == []:
            index_remove.append(e)

    aux_index = 0
    for e in range(len(index_remove)):
        p = index_remove[e] - aux_index
        leaves4pairs.pop(p)
        aux_index+=1


    leaves=[]
    spines=[]
    super_spines=[]
    border=[]

    #Condition to check if topology is greater than one pod
    if len(all_hop_count) == 0:
        return [], [], [], []

    max_min_hop_count = int(max(all_hop_count))

    if max_min_hop_count < 4: #It is a one Pod topology
        #Flattens pairs of group and removes repeated groups
        leaves1_temp = [item for sublist in leaves1pairs for item in sublist]
        leaves1 = []
        if len(leaves1_temp) > 0:
            nodes = leaves1_temp[0][0]
            leaves1.append(leaves1_temp[0])
            for i in range(1,len(leaves1_temp)): 
                if len(intersect(nodes,leaves1_temp[i][0]))==0:
                    leaves1.append(leaves1_temp[i])
                    nodes = nodes + leaves1_temp[i][0]
        
        max_neighbors_w_1_hop = 0
        a_known_spine = [[],[]]
        for i in range(len(leaves1)):
            if len(leaves1[i][0]) <= len(leaves1[i][1]) and len(leaves1[i][1]) > max_neighbors_w_1_hop:
                spines = []
                a_known_spine = [[],[]]
                for e in range(len(leaves1[i][0])):
                    if leaves1[i][0][e] not in spines:
                        a_known_spine[0].append(leaves1[i][0][e])
                        a_known_spine[1] = leaves1[i][1]
                        spines.append(leaves1[i][0][e])
                        max_neighbors_w_1_hop = len(leaves1[i][1])

        if max_min_hop_count > 1: #uncompleted connections set
            not_in = False
            for e in range(len(eqgroups)):
                if len(intersect(eqgroups[e][1], a_known_spine[1])) != 0 and eqgroups[e] != a_known_spine and eqgroups[e] != [[],[]] and eqgroups[e] != [[0],[0]]:
                    for x in range(len(eqgroups[e][1])):
                        if eqgroups[e][1][x] not in a_known_spine[1]:
                            not_in = True
                        
                    if not not_in:
                        for l in range(len(eqgroups[e][0])):
                            if eqgroups[e][0][l] not in spines:
                                spines.append(eqgroups[e][0][l])
        
        nodes = [e for e in range(numNodes)]
        nodes.pop(0)
        setdiff = list(set(nodes) - set(spines))   
        leaves = leaves + setdiff

    else:#It is a more than 1 Pod topology
        #Flattens pairs of group and removes repeated groups
        leaves4_temp = [item for sublist in leaves4pairs for item in sublist]
        leaves4 = []
        if len(leaves4_temp) > 0:
            nodes = leaves4_temp[0][0]
            leaves4.append(leaves4_temp[0])
            for i in range(1,len(leaves4_temp)): 
                if len(intersect(nodes,leaves4_temp[i][0]))==0:
                    leaves4.append(leaves4_temp[i])
                    nodes = nodes + leaves4_temp[i][0]
            
            #Although some leaves may not be connected to all spines, they should be 
            #included in the respective group in leaves4
            indexes_zeroed = []
            for i in range(len(leaves4)):
                for j in range(len(leaves4)):
                    if not (leaves4[i] == leaves4[j]): #Check if list i is not the same as list j
                        if len(intersect(leaves4[i][1], leaves4[j][1])) != 0:
                            if len(leaves4[i][1])<=len(leaves4[j][1]):
                                aux_rol = True
                                #Check if all the neighbors are in the other group's neighbors.
                                #OBSERVATION: All pods must have at least one leaf with completed connections.
                                for e in range(len(leaves4[i][1])):
                                    if leaves4[i][1][e] not in leaves4[j][1]:
                                        aux_rol = False
                                    
                                if aux_rol:
                                    leaves4[i][0] = leaves4[i][0] + leaves4[j][0]
                                    setdiff = list(set(leaves4[j][1]) - set(leaves4[i][1]))
                                    leaves4[i][1] = leaves4[i][1] + setdiff
                                    leaves4[j][0] = 0
                                    leaves4[j][1] = 0
                                    indexes_zeroed.append(j)
            #Remove zeroed groups
            indexes_zeroed.sort() #if not sorted, it would eventually remove undesired positions, since in each removal, the lists positions are changed (e.g. by removing position 3, position 5 becomes position 4)
            ctr_index = 0
            if len(indexes_zeroed) > 0:
                for i in range(len(indexes_zeroed)):
                    index = indexes_zeroed[i] - ctr_index
                    leaves4.pop(index)
                    ctr_index+=1
            
            #Assign the roles
            for i in range(len(leaves4)):
                for s in leaves4[i][0]:
                    if s not in leaves:
                        leaves.append(s)
            for i in range(len(leaves4)):
                for s in leaves4[i][1]:
                    if s not in spines and s not in leaves:
                        spines.append(s)
            for i in range(len(leaves4)):
                #Retrieve super-spines
                for e in range(len(eqgroups)):
                    if len(intersect(leaves4[i][1], eqgroups[e][0])) != 0:
                        for l in range(len(eqgroups[e][1])):
                            if (eqgroups[e][1][l] not in leaves4[i][0]) and (eqgroups[e][1][l] not in super_spines) and (eqgroups[e][1][l] not in leaves) and (eqgroups[e][1][l] not in spines):
                                super_spines.append(eqgroups[e][1][l])
                    
            #Retrieve border-leaves (the nodes left in the topology)
            set_nodes = leaves + spines + super_spines
            nodes = [e for e in range(numNodes)]
            nodes.pop(0)
            
            border = list(set(nodes) - set(set_nodes))    

    return leaves, spines, super_spines, border 