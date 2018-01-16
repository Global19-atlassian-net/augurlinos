import numpy as np
from util import (read_sequence_meta_data, read_tree_meta_data,
                  get_genes_and_alignments, generic_argparse)
from filenames import (tree_newick, tree_json, tree_sequence_alignment,
                       sequence_json, diversity_json, color_maps, meta_json)
from util import write_json, load_features, diversity_statistics, load_lat_long_defs
from Bio import Phylo


def tree_to_json(node, extra_attr = []):
    tree_json = {}
    str_attr = ['strain']
    num_attr = ['num_date']
    if hasattr(node, 'name'):
        tree_json['strain'] = node.name

    for prop in str_attr:
        if hasattr(node, prop):
            tree_json[prop] = node.__getattribute__(prop)
    for prop in num_attr:
        if hasattr(node, prop):
            try:
                tree_json[prop] = round(node.__getattribute__(prop),5)
            except:
                print("cannot round:", node.__getattribute__(prop), "assigned as is")
                tree_json[prop] = node.__getattribute__(prop)

    for prop in extra_attr:
        if len(prop)==2 and callable(prop[1]):
            if hasattr(node, prop[0]):
                tree_json[prop] = prop[1](node.__getattribute__(prop[0]))
        else:
            if hasattr(node, prop):
                tree_json[prop] = node.__getattribute__(prop)

    tree_json['tvalue'] = tree_json['num_date']
    if node.clades:
        tree_json["children"] = []
        for ch in node.clades:
            tree_json["children"].append(tree_to_json(ch, extra_attr))
    return tree_json


def attach_tree_meta_data(T, node_meta):
    def parse_mutations(muts):
        return muts.split(',') if type(muts) in [str, unicode] else ""

    for n in T.find_clades(order='preorder'):
        n.attr={}
        n.aa_muts={}
        for field, val in node_meta[n.name].items():
            if 'mutations' in field:
                if field=='mutations':
                    muts = parse_mutations(val)
                    if muts:
                        n.__setattr__('muts', muts)
                else:
                    prot = '_'.join(field.split('_')[:-1])
                    muts = parse_mutations(val)
                    if muts:
                        n.aa_muts[prot] = muts
            elif field in ['branch_length', 'mutation_length', 'clock_length',
                           'clade', 'num_date']:
                n.__setattr__(field, val)
                n.attr[field] = val
            else:
                n.attr[field] = val



    T.root.attr['div']=0
    for n in T.get_nonterminals(order='preorder'):
        for c in n:
            bl =  n.mutation_length if hasattr(n, "mutation_length") else "branch_length"
            c.attr["div"] = n.attr["div"] + bl



def export_sequence_json(T, path, prefix):
    from Bio import SeqIO
    plain_export = 0.99
    indent = None

    elems = {'root':{}}
    for node in T.find_clades():
        elems[node.clade] = {}

    for gene, aln_fname in get_genes_and_alignments(path, tree=True):
        seqs={}
        for seq in SeqIO.parse(aln_fname, 'fasta'):
            seqs[seq.name] = seq

        root_seq = seqs[T.root.name]
        elems['root'][gene] = "".join(root_seq)
        for node in T.find_clades():
            nseq = seqs[node.name]
            if hasattr(node, "clade"):
                differences = {pos:state for pos, (state, ancstate) in
                            enumerate(zip(nseq, elems['root'][gene]))
                            if state!=ancstate}
                if len(differences)<=plain_export*len(seq):
                    elems[node.clade][gene] = differences
                else:
                    elems[node.clade][gene] = seq

    fname = sequence_json(path, prefix)
    write_json(elems, fname, indent=indent)


def export_metadata_json(T, path, prefix, reference, indent=1):
    print("Writing out metaprocess")
    mjson = {}

    mjson["virus_count"] = T.count_terminals()
    from datetime import date
    mjson["updated"] = date.today().strftime('%Y-%m-%d')
    mjson["author_info"] = {
        "?": {
           "paper_url": "?",
           "journal": "?",
           "title": "?",
           "n": 1
        }}
    mjson["seq_author_map"] = {}

    from collections import defaultdict
    cmaps = defaultdict(list)
    with open(color_maps(path), 'r') as cfile:
        for line in cfile:
            try:
                trait, name, color = line.strip().split('\t')
            except:
                continue
            cmaps[trait].append((name, color))

    mjson["color_options"] = {
      "gt": {
           "menuItem": "genotype",
           "type": "discrete",
           "legendTitle": "Genotype",
           "key": "genotype"
          },
       "num_date": {
           "menuItem": "date",
           "type": "continuous",
           "legendTitle": "Sampling date",
           "key": "num_date"
          }}
    for trait in cmaps:
        mjson["color_options"][trait] = {
        "menuItem":trait,
        "type":"discrete",
        "color_map":cmaps[trait],
        "legendTitle":trait,
        "key":trait
        }

    mjson["panels"] = [
        "tree",
        "map",
        "entropy"
        ]
    mjson["title"] = "NextTB"
    mjson["maintainer"] = "Emma Hodcroft"
    mjson["geo"] = {}
    lat_long_defs = load_lat_long_defs()
    for geo_trait in ['region', "country"]:
        mjson["geo"][geo_trait] = {}
        for n in T.find_clades():
            place = n.attr[geo_trait]
            if  (place not in mjson["geo"][geo_trait]
                 and place in lat_long_defs):
                mjson["geo"][geo_trait][place] = lat_long_defs[place]

    mjson["commit"] = "unknown"
    mjson["filters"] = ["country", "region"]

    genes = load_features(reference)
    anno = {}
    for feat, aln_fname in get_genes_and_alignments(path, tree=False):
        if feat in genes:
            anno[feat] = {"start":int(genes[feat].location.start),
                          "end":int(genes[feat].location.end),
                          "strand":genes[feat].location.strand}
    mjson["annotations"] = anno
    write_json(mjson, meta_json(path,prefix), indent=indent)


def export_diversity(path, prefix, reference):
    '''
    write the alignment entropy of each alignment (nucleotide and translations) to file
    '''
    indent=None
    genes = load_features(reference)
    entropy_json = {}
    for feat, aln_fname in get_genes_and_alignments(path, tree=False):
        entropy = diversity_statistics(aln_fname, nuc=feat=='nuc')
        S = [max(0,round(x,4)) for x in entropy]
        n = len(S)
        if feat=='nuc':
            entropy_json[feat] = {'pos':range(0,n), 'codon':[x//3 for x in range(0,n)], 'val':S}
        elif feat in genes:
            entropy_json[feat] = {'pos':[x for x in genes[feat]][::3],
                                  'codon':range(n), 'val':S}
    write_json(entropy_json, diversity_json(path, prefix), indent=indent)


def tree_layout(T):
    yval=T.count_terminals()
    for n in T.find_clades(order='postorder'):
        if n.is_terminal():
            n.yvalue=yval
            yval-=1
        else:
            child_yvalues = [c.yvalue for c in n]
            n.yvalue=0.5*(np.min(child_yvalues)+np.max(child_yvalues))
        n.xvalue = n.attr['div']



if __name__ == '__main__':
    parser =  generic_argparse("Export precomputed data as auspice jsons")
    parser.add_argument('--prefix', required=True,
                        help="prefix for json files that are passed on to auspice (e.g., zika.fasta)")
    parser.add_argument('--reference',
                        help="reference sequence needed for entropy feature export")
    parser.add_argument('--no_sequence', action="store_true",
                        help="")
    parser.add_argument('--no_meta', action="store_true",
                        help="")
    parser.add_argument('--no_diversity', action="store_true",
                        help="")

    args = parser.parse_args()
    path = args.path

    T = Phylo.read(tree_newick(path), 'newick')
    seq_meta = read_sequence_meta_data(path)
    tree_meta = read_tree_meta_data(path)
    attach_tree_meta_data(T, tree_meta)
    tree_layout(T)
    fields_to_export = tree_meta.values()[0].keys()+["tvalue","yvalue", "xvalue", "attr", "muts", "aa_muts"]
    tjson = tree_to_json(T.root, extra_attr=fields_to_export)
    write_json(tjson, tree_json(path, args.prefix))

    if not args.no_sequence:
        export_sequence_json(T, path, args.prefix)

    if not args.no_diversity:
        export_diversity(path, args.prefix, args.reference)

    if not args.no_meta:
        export_metadata_json(T, path, args.prefix, args.reference)
