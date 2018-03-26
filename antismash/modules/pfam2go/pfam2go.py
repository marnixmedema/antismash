# License: GNU Affero General Public License v3 or later
# A copy of GNU AGPL v3 should have been included in this software package in LICENSE.txt.

# initial test if approach even works... later, maybe check for Pfam ids of interest first and only work with these?

#from antismash.common.secmet.feature import Feature, FeatureLocation
import logging
import os
import timeit
from collections import defaultdict
from typing import Any, Dict, List

from Bio.Alphabet import generic_dna
from Bio.Seq import Seq
from Bio.SeqFeature import FeatureLocation
from antismash.common import path
from antismash.common.module_results import ModuleResults
from antismash.common.secmet.feature import PFAMDomain
from antismash.common.secmet.record import Record


class GeneOntology:
    def __init__(self, _id: str, description: str):
        if not _id.startswith('GO:'):
            raise ValueError('Invalid Gene Ontology ID: {0}'.format(_id))
        self.id = _id
        assert isinstance(description, str)
        self.description = description

    def __str__(self):
        return self.id


class GeneOntologies:
    def __init__(self, pfam: str, gos: List[GeneOntology]):
        self.pfam = str(pfam)
        assert isinstance(gos, list) and gos
        self.go_entries = gos

    def __str__(self) -> str:
        return str([str(go_entry) for go_entry in self.go_entries])


class Pfam2GoResults(ModuleResults):
    """Holds results for Pfam to Gene Ontology module."""
    # schema version needed?
    def __init__(self, record_id: str, pfam_domains_with_gos: Dict[PFAMDomain, List[GeneOntologies]]):
        super().__init__(record_id)
        #  store mapping of PFAM domain ID and GO terms
        self.pfam_domains_with_gos = pfam_domains_with_gos

    def add_to_record(self, record: Record):
        if record.id != self.record_id:
            raise ValueError("Record to store in and record analysed don't match")
        for domain, all_ontologies in self.pfam_domains_with_gos.items():
            # TODO: currently replaces all gene ontologies
            #domain.gene_ontologies = all_ontologies
            domain.gene_ontologies['pfam2go'] = all_ontologies

    def to_json(self) -> Dict[str, Any]:
        """ Construct a JSON representation of this instance """
        # first, awful attempt
        jsonfile = {"pfams": {}, "record_id": self.record_id}
        for pfam, all_ontologies in self.pfam_domains_with_gos.items():
            for ontologies in all_ontologies:
                jsonfile["pfams"][ontologies.pfam] = [(str(go_entry), go_entry.description)
                                                      for go_entry in ontologies.go_entries]
        return jsonfile

    @staticmethod
    def from_json(json: Dict[str, Any], record) -> "Pfam2GoResults":
        """ Constructs a new Pfam2GoResults instance from a json format and the
            original record analysed.
        """
        #  schema version check?
        #  record id check?
        all_pfam_ids_to_ontologies = defaultdict(list)
        for domain in record.get_pfam_domains():
            for pfam_id in domain.db_xref:
                id_without_version = pfam_id.partition('.')[0]
                if id_without_version in json["pfams"]:
                    all_ontology = [GeneOntology(goid_desc_pair[0], goid_desc_pair[1])
                                    for goid_desc_pair in json["pfams"][id_without_version]]
                    all_pfam_ids_to_ontologies[domain].append(GeneOntologies(id_without_version, all_ontology))
        results = Pfam2GoResults(record.id, all_pfam_ids_to_ontologies)
        return results


def parse_all_mappings(mapfile):
    go_ids_by_pfam = defaultdict(list)
    go_desc_by_id = {}
    with open(path.get_full_path(__file__, mapfile), 'r') as pfam_map:
        for line in pfam_map:
            if line.startswith('!'):
                continue
            both_info = line.split(' > ')
            pfam_info = both_info[0]
            go_info = both_info[1].strip()
            pfam_split = pfam_info.split(' ')
            pfam_id = pfam_split[0].replace('Pfam:', '')
            go_split = go_info.split(' ; ')
            go_id = go_split[1]
            go_readable = go_split[0].replace('GO:', '')
            go_ids_by_pfam[pfam_id].append(go_id)
            go_desc_by_id[go_id] = go_readable
    return go_ids_by_pfam, go_desc_by_id


def build_as_i_go(mapfile) -> Dict[str, GeneOntologies]:
    results = {}
    gene_ontology_per_pfam = defaultdict(list)
    with open(path.get_full_path(__file__, mapfile), 'r') as pfam_map:
        for line in pfam_map:
            if line.startswith('!'):
                continue
            both_info = line.split(' > ')
            pfam_info = both_info[0]
            go_info = both_info[1].strip()
            pfam_split = pfam_info.split(' ')
            pfam_id = pfam_split[0].replace('Pfam:', '')
            go_split = go_info.split(' ; ')
            go_id = go_split[1]
            go_readable = go_split[0].replace('GO:', '')
            gene_ontology_per_pfam[pfam_id].append(GeneOntology(go_id, go_readable))
    for pfam, ontology_list in gene_ontology_per_pfam.items():
        results[pfam] = GeneOntologies(pfam, ontology_list)
    return results


def construct_gene_ontologies(pfam: str, go_ids: List, go_desc_by_id: Dict) -> GeneOntologies:
    gene_ontologies = []
    for go_id in go_ids:
        if go_id not in go_desc_by_id:
            raise ValueError('Gene Ontology ID has no associated description: %s.' % go_id)
        gene_ontology = GeneOntology(go_id, go_desc_by_id[go_id])
        gene_ontologies.append(gene_ontology)
    return GeneOntologies(pfam, gene_ontologies)


def build_at_the_end(go_ids_by_pfam: Dict, go_desc_by_id: Dict) -> Dict[str, GeneOntologies]:
    results = {}
    for pfam in go_ids_by_pfam:
        construction = construct_gene_ontologies(pfam, go_ids_by_pfam[pfam], go_desc_by_id)
        results[pfam] = construction
    return results


def get_gos_for_pfams(record) -> Dict[PFAMDomain, List[GeneOntologies]]:
    pfam_domains_with_gos = defaultdict(list)
    pfams = record.get_pfam_domains()
    full_gomap_as_ontologies = build_as_i_go('pfam2go-march-2018.txt')
    if not pfams:
        logging.info('No Pfam domains found')
    for pfam in pfams:
        pfam_ids = pfam.db_xref
        if not pfam_ids:
            logging.info('No Pfam ids found')
        for pfam_id in pfam_ids:
            pfam_id = pfam_id.partition('.')[0]  # strip out version number; supposedly faster than split
            if not pfam_id.isalnum() or not pfam_id.startswith('PF'):
                # invalid ID shouldn't break anything, but should be noticed
                logging.warning('Pfam id {0} is not a valid Pfam id, skipping'.format(pfam_id))
            gene_ontologies_for_pfam = full_gomap_as_ontologies.get(pfam_id, False)
            if gene_ontologies_for_pfam:
                pfam_domains_with_gos[pfam].append(gene_ontologies_for_pfam)
    return pfam_domains_with_gos


if __name__ == '__main__':
    build_as_i_go_stmt = """data = 'pfam2go-march-2018.txt'
build_as_i_go(data)
    """

    build_at_the_end_statement = """data = 'pfam2go-march-2018.txt'
go_ids_by_pfam, go_desc_by_id = parse_all_mappings(data)
build_at_the_end(go_ids_by_pfam, go_desc_by_id)
    """

    def build_fake_record():
        fake_record = Record(Seq("ATGTTATGAGGGTCATAACAT", generic_dna))
        fake_pfam_location = FeatureLocation(0, 12)
        fake_pfam = PFAMDomain(location=fake_pfam_location, description='MCPsignal')
        fake_pfam.db_xref = ['PF02364']
        fake_record.add_pfam_domain(fake_pfam)
        return fake_record

    setup_to_json = """from __main__ import build_fake_record, get_gos_for_pfams, Pfam2GoResults
fake_record = build_fake_record()
results = Pfam2GoResults(fake_record.id, get_gos_for_pfams(fake_record))
    """
    setup_from_json =  """from __main__ import build_fake_record, get_gos_for_pfams, Pfam2GoResults
fake_record = build_fake_record()
results = Pfam2GoResults(fake_record.id, get_gos_for_pfams(fake_record))
results_to_json = results.to_json()
    """

    #print(timeit.repeat(stmt=build_as_i_go_stmt, number=10, repeat=3, setup='from __main__ import build_as_i_go'))
    #print(timeit.repeat(stmt=build_at_the_end_statement, number=10, repeat=3, setup='from __main__ import build_at_the_end, parse_all_mappings'))
    print(timeit.repeat(stmt='results_to_json = results.to_json()', number=10000, repeat=3, setup=setup_to_json))
    print(timeit.repeat(stmt='results_from_json = Pfam2GoResults.from_json(results_to_json, fake_record)', number=10000,
                        repeat=3, setup=setup_from_json))