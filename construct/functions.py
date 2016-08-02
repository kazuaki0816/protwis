from protein.models import Protein, ProteinConformation
from residue.models import Residue
from structure.models import Structure
from construct.models import *

from ligand.models import Ligand, LigandType, LigandRole
from ligand.functions import get_or_make_ligand

from common.tools import fetch_from_web_api
from urllib.parse import quote
from string import Template
from urllib.request import urlopen
from operator import itemgetter
from itertools import groupby
import time
import json
import datetime

AA_three = {'CYS': 'C', 'ASP': 'D', 'SER': 'S', 'GLN': 'Q', 'LYS': 'K',
     'ILE': 'I', 'PRO': 'P', 'THR': 'T', 'PHE': 'F', 'ASN': 'N', 
     'GLY': 'G', 'HIS': 'H', 'LEU': 'L', 'ARG': 'R', 'TRP': 'W', 
     'ALA': 'A', 'VAL':'V', 'GLU': 'E', 'TYR': 'Y', 'MET': 'M'}

# def look_for_value(d,k):
#     ### look for a value in dict if found, give back, otherwise None


def fetch_pdb_info(pdbname,protein):
    d = {}
    d['construct_crystal'] = {}
    d['construct_crystal']['pdb'] = pdbname
    d['construct_crystal']['pdb_name'] = 'auto_'+pdbname
    d['construct_crystal']['uniprot'] = protein.parent.entry_name

    d['contact_info'] = {}
    d['contact_info']['name_cont'] = 'gpcrdb'
    d['contact_info']['pi_email'] = 'info@gpcrdb.org'
    d['contact_info']['pi_name'] = 'gpcrdb'
    d['contact_info']['url'] = 'gpcrdb.org'
    d['contact_info']['date'] = time.strftime('%m/%d/%Y')
    d['contact_info']['address'] = ''

    d['protein'] = protein.parent.name
    d['wt_seq'] = protein.parent.sequence
    d['pdb'] = pdbname
    d['links'] = []
    d['xml_not_observed'] = []
    d['xml_segments'] = []

    pos_in_wt = list(range(1,len(d['wt_seq'])+1))

    #http://files.gpcrdb.org/uniprot_mapping.txt
    ## get uniprot to name mapping
    url = 'http://files.gpcrdb.org/uniprot_mapping.txt'
    req = urlopen(url)
    uniprot_mapping = req.read().decode('UTF-8')
    rows = ( line.split(' ') for line in uniprot_mapping.split('\n') )
    uniprot_mapping = { row[0]:row[1:] for row in rows }
    # print(uniprot_mapping)

    #ftp://ftp.ebi.ac.uk/pub/databases/msd/sifts/xml/1xyz.xml.gz
    cache_dir = ['sifts', 'xml']
    url = 'ftp://ftp.ebi.ac.uk/pub/databases/msd/sifts/xml/$index.xml.gz'
    sifts = fetch_from_web_api(url, pdbname.lower(), cache_dir, xml = True)
    d['links'].append(Template(url).substitute(index=quote(str(pdbname.lower()), safe='')))
    d['mutations'] = []
    d['auxiliary'] = {}
    receptor_seq_ids = []
    if sifts: #success
        # print(sifts)
        insert_position = 'N-term'
        insert_start = 0
        for elem in sifts.find('.//{http://www.ebi.ac.uk/pdbe/docs/sifts/eFamily.xsd}entity'):
            seg_uniprot_ids = []
            max_pos = 0
            min_pos = 99999
            pos_list = []
            uniprot_pos = None
            receptor = False
            u_id = 'N/A'
            u_id_source = 'N/A'
            for res in elem[0]: #first element is residuelist
                for node in res:
                    if node.tag == '{http://www.ebi.ac.uk/pdbe/docs/sifts/eFamily.xsd}crossRefDb':
                        source = node.attrib['dbSource']
                        if source=='UniProt':
                            u_id = node.attrib['dbAccessionId']
                            u_id_source = 'UniProt'
                            if u_id in uniprot_mapping:
                                u_id = uniprot_mapping[u_id][0] 
                                receptor = True ## this is receptor element
                                insert_position = 'Within Receptor'
                            if u_id not in seg_uniprot_ids:
                                seg_uniprot_ids.append(u_id)
                            uniprot_pos = int(node.attrib['dbResNum'])
                            uniprot_aa = node.attrib['dbResName']
                        elif source=='PDB':
                            pos = int(node.attrib['dbResNum'])
                            pdb_aa = AA_three[node.attrib['dbResName'].upper()]
                            if receptor:
                                receptor_seq_ids.append(pos)
                            if pos>max_pos: max_pos = pos
                            if pos<min_pos: min_pos = pos
                    elif node.tag == '{http://www.ebi.ac.uk/pdbe/docs/sifts/eFamily.xsd}residueDetail':
                        #print(node.attrib['property'],node.text)
                        if node.text=='Not_Observed' and receptor:
                            d['xml_not_observed'].append(uniprot_pos)
                        elif node.attrib['property']=='Annotation' and u_id=='N/A':
                            u_id = node.text
                            if u_id not in seg_uniprot_ids:
                                seg_uniprot_ids.append(u_id)
                        elif node.attrib['property']=='Annotation' and node.text == 'Engineered mutation':
                            d['mutations'].append({'mut':pdb_aa,'wt':uniprot_aa,'pos':uniprot_pos})
                if uniprot_pos:
                    pos_list.append(uniprot_pos)
                    if receptor:
                       pos_in_wt.remove(uniprot_pos)
                       insert_start =  str(uniprot_pos+1)
            ranges = []
            for k, g in groupby(enumerate(pos_list), lambda x:x[0]-x[1]):
                group = list(map(itemgetter(1), g))
                ranges.append((group[0], group[-1]))

            if receptor==False and u_id_source=='UniProt':
                url = 'http://www.uniprot.org/uniprot/$index.xml'
                insert_info = fetch_from_web_api(url, seg_uniprot_ids[0], cache_dir, xml = True)
                d['links'].append(Template(url).substitute(index=quote(str(seg_uniprot_ids[0]), safe='')))

                for elm in insert_info.findall('.//{http://uniprot.org/uniprot}recommendedName'):
                    seg_uniprot_ids[0] = elm.find('{http://uniprot.org/uniprot}fullName').text

            d['xml_segments'].append([elem.attrib['segId'],seg_uniprot_ids,min_pos,max_pos,ranges,insert_position])
            if receptor == False:
                d['auxiliary']['aux'+str(len(d['auxiliary']))] = {'type':'auto','subtype':seg_uniprot_ids[0],'presence':'YES','position':insert_position, 'start':insert_start}
        d['deletions'] = []
        for k, g in groupby(enumerate(pos_in_wt), lambda x:x[0]-x[1]):
            group = list(map(itemgetter(1), g))
            d['deletions'].append({'start':group[0], 'end':group[-1], 'origin':'user'})

        d['not_observed'] = []
        for k, g in groupby(enumerate(d['xml_not_observed']), lambda x:x[0]-x[1]):
            group = list(map(itemgetter(1), g))
            d['not_observed'].append((group[0], group[-1]))

    else:
        print('failed sifts')

    #http://www.ebi.ac.uk/pdbe/api/pdb/entry/experiment/2RH1
    ## experiment data
    cache_dir = ['pdbe', 'experiment']
    url = 'http://www.ebi.ac.uk/pdbe/api/pdb/entry/experiment/$index'
    pdbe = fetch_from_web_api(url, pdbname, cache_dir)
    d['links'].append(Template(url).substitute(index=quote(str(pdbname), safe='')))
    if pdbe: #success
        r = pdbe[pdbname.lower()][0]
        d['resolution'] = r.get('resolution')
        d['crystal_growth'] = r.get('crystal_growth')
        d['r_factor'] = r.get('r_factor')
        d['experimental_method'] = r.get('experimental_method')
    else:
        print('failed pdbe')

    # #http://www.ebi.ac.uk/pdbe/api/pdb/entry/modified_AA_or_NA/2RH1
    # ## modified AA (empty on 2RH1)
    # cache_dir = ['pdbe', 'modified_AA_or_NA']
    # url = 'http://www.ebi.ac.uk/pdbe/api/pdb/entry/modified_AA_or_NA/$index'
    # pdbe_mod = fetch_from_web_api(url, pdbname, cache_dir)
    # d['links'].append(Template(url).substitute(index=quote(str(pdbname), safe='')))
    
    # if pdbe_mod: #success
    #     print(pdbe_mod)
    # else:
    #     d['modifications3'] = 'None'
    #     print('failed pdbe_mod')

    #http://www.rcsb.org/pdb/explore/jmol.do?structureId=4LDO&json=true
    ## modifications for their jmol -- "hacky" way to get it
    cache_dir = ['rcsb', 'jmol_modifications']
    url = 'http://www.rcsb.org/pdb/explore/jmol.do?structureId=$index&json=true'
    rcsb_mod = fetch_from_web_api(url, pdbname, cache_dir)
    d['links'].append(Template(url).substitute(index=quote(str(pdbname), safe='')))

    if rcsb_mod: #success
        d['modifications'] = []
        d['modifications2'] = rcsb_mod
        # print(receptor_seq_ids)
        for mod in rcsb_mod['protmod']['domains']:
            t = mod['range'].split(',')
            pair = [t[0].split(':')[0],t[1].split(':')[0]]
            # print(mod['id'],pair,mod['description'])
            d['modifications'].append({'position':['pair',pair],'type':mod['id'],'remark':mod['description']})
            #{{v.id}} {{v.range}} {{v.description}} {{v.pdbCcId}} <br><br>
   
    else:
        d['modifications2'] = 'None'
        print('failed pdbe_mod')

    #http://www.ebi.ac.uk/pdbe/api/pdb/entry/mutated_AA_or_NA/2RH1
    ## mutated AA
    ### got conflicts, engerineered mutation and expression tag examples
    cache_dir = ['pdbe', 'mutated_AA_or_NA']
    url = 'http://www.ebi.ac.uk/pdbe/api/pdb/entry/mutated_AA_or_NA/$index'
    pdbe_mut = fetch_from_web_api(url, pdbname, cache_dir)
    d['links'].append(Template(url).substitute(index=quote(str(pdbname), safe='')))
    
    if pdbe_mut: #success
        r = pdbe_mut[pdbname.lower()]
        d['mutations_pdbe'] = []
        for mut in r:
            mut_from = mut['mutation_details']['from']
            mut_to = mut['mutation_details']['to']
            mut_type = mut['mutation_details']['type']
            construct_seq_number = mut['residue_number']
            wt_seq_number = mut['author_residue_number']
            t = {'wt':mut_from,'mut':mut_to,'type':mut_type,'c_seq_nr':construct_seq_number,'pos':wt_seq_number}
            d['mutations_pdbe'].append(t)
    else:
        print('failed pdbe_mut')


    #http://www.rcsb.org/pdb/rest/das/pdb_uniprot_mapping/alignment?query=2RH1
    ## uniprot mappings
    ### seems to be IDs of stuff then use:
    # http://www.uniprot.org/uniprot/P00720.xml
    cache_dir = ['rcsb', 'pdb_uniprot_mapping']
    url = 'http://www.rcsb.org/pdb/rest/das/pdb_uniprot_mapping/alignment?query=$index'
    uniprot_map = fetch_from_web_api(url, pdbname, cache_dir, xml = True)
    d['links'].append(Template(url).substitute(index=quote(str(pdbname), safe='')))
    
    if uniprot_map: #success
        inserts = {}
        inserts_fixed = {}
        for block in uniprot_map[0]:
            if block.tag[-5:]!='block':
                continue #only interested in the blocks...
            i = 0
            for segment in block:
                if i==0:
                    construct_range = [segment.attrib['start'],segment.attrib['end']]
                else:
                    insert_range = [segment.attrib['start'],segment.attrib['end']]
                    insert_id = segment.attrib['intObjectId']
                prev_block = segment
                i += 1
            i = inserts.setdefault(insert_id, [])
            i.append({'c':construct_range,'i':insert_range})
        for insert,blocks in inserts.items():

            if insert in uniprot_mapping:
                insert = uniprot_mapping[insert][0] 

            inserts_fixed[insert] = {}
            cache_dir = ['uniprot', 'id']
            url = 'http://www.uniprot.org/uniprot/$index.xml'
            insert_info = fetch_from_web_api(url, insert, cache_dir, xml = True)
            d['links'].append(Template(url).substitute(index=quote(str(insert), safe='')))

            for elm in insert_info.findall('.//{http://uniprot.org/uniprot}recommendedName'):
                inserts_fixed[insert]['alt_name'] = elm.find('{http://uniprot.org/uniprot}fullName').text
            # print(insert_info.findall('.//.'))

            blocks_num = len(blocks)
            prev_block = None
            temp = []
            for i, b in enumerate(blocks): #for each block, to glue them together
                if i==0:
                    start = [b['i'][0],b['c'][0]]
                    end = [b['i'][1],b['c'][1]]
                # print(i,b)
                if i<blocks_num-1: #if not last
                    # print('cur',b,'next',blocks[i+1])
                    if int(b['i'][1])==int(blocks[i+1]['i'][0])-1 and int(b['c'][1])==int(blocks[i+1]['c'][0])-1:
                        #if insert is a contination #if construct continues
                        end = [blocks[i+1]['i'][1],blocks[i+1]['c'][1]]
                    else:
                        #gap
                        temp.append({'i_start':start[0],'i_end':end[0],'c_start':start[1],'c_end':end[1]})
                        # temp.append([start,end])
                        start = [blocks[i+1]['i'][0],blocks[i+1]['c'][0]]
                        end = [blocks[i+1]['i'][1],blocks[i+1]['c'][1]]
            temp.append({'i_start':start[0],'i_end':end[0],'c_start':start[1],'c_end':end[1]})
            i = inserts_fixed[insert].setdefault('positions', [])
            i.append(temp)

        d['inserts'] = inserts_fixed


    else:
        print('failed uniprot_map')

    return d


def add_construct(d):
    protein = Protein.objects.filter(entry_name=d['construct_crystal']['uniprot']).get()
    structure = Structure.objects.filter(pdb_code__index=d['construct_crystal']['pdb'].upper()).get()
    protein_conformation = structure.protein_conformation

    construct = Construct()
    construct.protein = protein
    construct.name = d['construct_crystal']['pdb_name']
    construct.json = d
    construct.structure = structure

    #CrystalInfo
    crystal = CrystalInfo()
    crystal.resolution = structure.resolution
    crystal.pdb_data = structure.pdb_data
    crystal.pdb_code = structure.pdb_code.index
    crystal.save()

    construct.crystal = crystal

    #Contact INFO
    if 'contact_info' in d:
        construct.contributor, created = ContributorInfo.objects.get_or_create(name = d['contact_info']['name_cont'],
                                                       pi_email = d['contact_info']['pi_email'],
                                                       pi_name = d['contact_info']['pi_name'],
                                                       urls = d['contact_info']['url'],
                                                       date = datetime.datetime.strptime(d['contact_info']['date'], '%m/%d/%Y').strftime('%Y-%m-%d'),
                                                       address = d['contact_info']['address'])

    construct.save()
    #MUTATIONS
    for mutation in d['mutations']:
        mut = ConstructMutation.objects.create(sequence_number=mutation['pos'],wild_type_amino_acid=mutation['wt'],mutated_amino_acid=mutation['mut'])
        construct.mutations.add(mut)

    #DELETIONS
    insert_deletions = {}
    for deletion in d['deletions']:
        if 'start' in deletion:
            dele = ConstructDeletion.objects.create(start=deletion['start'],end=deletion['end'])
        else:
            dele = ConstructDeletion.objects.create(start=deletion['pos'],end=deletion['pos'])
        construct.deletions.add(dele)
        if deletion['origin']!='user':
            id = deletion['origin'].split('_')[1]
            insert_deletions[id] = deletion

    #INSERTIONS (AUX)
    for name,aux in d['auxiliary'].items():
        id = name.replace('aux','')
        aux_type,created = ConstructInsertionType.objects.get_or_create(name=aux['type'],subtype=aux['subtype'])
        insert = ConstructInsertion.objects.create(insert_type=aux_type,presence=aux['presence'],position=aux['position']+"_"+id)

        if insert.presence == 'YES' and insert.position.startswith('Within Receptor'):
            #need to fetch range
            if aux['start']:
                insert.start = aux['start']
                insert.end = aux['start']
            else:
                insert.start = insert_deletions[id]['start']
                insert.end = insert_deletions[id]['end']
            insert.save()

        construct.insertions.add(insert)

    #MODIFICATIONS
    for modification in d['modifications']:
        mod = ConstructModification.objects.create(modification=modification['type'],position_type=modification['position'][0],
                                                   pos_start=modification['position'][1][0],
                                                   pos_end=modification['position'][1][1],remark=modification['remark'] )
        construct.modifications.add(mod)


    #EXPRESSION
    if 'expression' in d:
        construct.expression,created = ExpressionSystem.objects.get_or_create(expression_method=d['expression']['expr_method'],
                                                        host_cell_type=d['expression']['host_cell_type'],
                                                        host_cell=d['expression']['host_cell'],
                                                        remarks=d['expression']['expr_remark'])


    
    #solubilization
    if 'solubilization' in d:
        c_list = ChemicalList()
        list_name,created  = ChemicalListName.objects.get_or_create(name='Solubilization')
        c_list.name = list_name
        c_list.save()
        ct, created = ChemicalType.objects.get_or_create(name='detergent')
        chem, created = Chemical.objects.get_or_create(name=d['solubilization']['deterg_type'], chemical_type=ct)
        cc, created = ChemicalConc.objects.get_or_create(concentration=d['solubilization']['deterg_concentr'], concentration_unit=d['solubilization']['deterg_concentr_unit'], chemical=chem)
        c_list.chemicals.add(cc)                
        ct, created = ChemicalType.objects.get_or_create(name='additive')
        chem, created = Chemical.objects.get_or_create(name=d['solubilization']['solub_additive'], chemical_type=ct)
        cc, created = ChemicalConc.objects.get_or_create(concentration=d['solubilization']['additive_concentr'], concentration_unit=d['solubilization']['addit_concentr_unit'], chemical=chem)
        c_list.chemicals.add(cc)

        solubilization = Solubilization.objects.create(chemical_list = c_list)

        construct.solubilization = solubilization
        construct.save()

        #Purification
        purification = Purification.objects.create()
        for puri,step in d['solubilization'].items():
            if not puri.startswith(('chem_enz_treatment','sol_remark')):
                continue
            else:
                s,created = PurificationStep.objects.get_or_create(name=step)
                purification.steps.add(s)
                print(step)
        construct.purification = purification
    construct.save()

    #CRYSTALLIZATION 
    if 'crystallization' in d:
        c = Crystallization()
        sub_name = "" if 'lcp_lipid' not in d['crystallization'] else d['crystallization']['lcp_lipid']
        c_type, created = CrystallizationTypes.objects.get_or_create(name=d['crystallization']['crystal_type'], sub_name=sub_name)
        c_method, created = CrystallizationMethods.objects.get_or_create(name=d['crystallization']['crystal_method'])

        c.crystal_type = c_type
        c.crystal_method = c_method
        c.remarks = d['crystallization']['crystal_remark']
        c.temp = d['crystallization']['temperature']

        if d['crystallization']['ph']=='single_ph':
            c.ph_start = d['crystallization']['ph_single']
            c.ph_end = d['crystallization']['ph_single']
        else:
            c.ph_start = d['crystallization']['ph_range_one']
            c.ph_end = d['crystallization']['ph_range_two']


        c.protein_conc = d['crystallization']['protein_concentr']
        c.protein_conc_unit = d['crystallization']['protein_conc_unit']

        c.json = d
        c.save()

        #MAKE LISTS
        c_list = ChemicalList()
        list_name,created  = ChemicalListName.objects.get_or_create(name='crystallization_chemical_components')
        c_list.name = list_name
        c_list.save()
        for chemical in d['crystallization']['chemical_components']:
            ct, created = ChemicalType.objects.get_or_create(name='crystallization_chemical_components')
            chem, created = Chemical.objects.get_or_create(name=chemical['component'], chemical_type=ct)
            cc, created = ChemicalConc.objects.get_or_create(concentration=chemical['value'], concentration_unit=chemical['unit'], chemical=chem)
            c_list.chemicals.add(cc)
        c.chemical_lists.add(c_list)

        if d['crystallization']['crystal_type']=='lipidic cubic phase': #make list of LCP stuff
            c_list = ChemicalList()
            # c_list.name = d['crystallization']['lcp_lipid']
            list_name,created  = ChemicalListName.objects.get_or_create(name='LCP')
            c_list.name = list_name
            c_list.save()
            ct, created = ChemicalType.objects.get_or_create(name='LCP Lipid additive')
            chem, created = Chemical.objects.get_or_create(name=d['crystallization']['lcp_add'], chemical_type=ct)
            cc, created = ChemicalConc.objects.get_or_create(concentration=d['crystallization']['lcp_conc'], concentration_unit=d['crystallization']['lcp_conc_unit'], chemical=chem)
            c_list.chemicals.add(cc)
            c.chemical_lists.add(c_list)

        #DETERGENT
        c_list = ChemicalList()
        list_name,created  = ChemicalListName.objects.get_or_create(name='Detergent')
        c_list.name = list_name
        c_list.save()
        ct, created = ChemicalType.objects.get_or_create(name='detergent')
        chem, created = Chemical.objects.get_or_create(name=d['crystallization']['detergent'], chemical_type=ct)
        cc, created = ChemicalConc.objects.get_or_create(concentration=d['crystallization']['deterg_conc'], concentration_unit=d['crystallization']['deterg_conc_unit'], chemical=chem)
        c_list.chemicals.add(cc)
        c.chemical_lists.add(c_list)

        #LIPID
        c_list = ChemicalList()
        list_name,created  = ChemicalListName.objects.get_or_create(name='Lipid')
        c_list.name = list_name
        c_list.save()
        ct, created = ChemicalType.objects.get_or_create(name='lipid')
        chem, created = Chemical.objects.get_or_create(name=d['crystallization']['lipid'], chemical_type=ct)
        cc, created = ChemicalConc.objects.get_or_create(concentration=d['crystallization']['lipid_concentr'], concentration_unit=d['crystallization']['lipid_concentr_unit'], chemical=chem)
        c_list.chemicals.add(cc)
        c.chemical_lists.add(c_list)



        #Use ligand function to get ligand if it exists or otherwise create. Lots of checks for inchi/smiles/name
        ligand = get_or_make_ligand(d['construct_crystal']['ligand_id'],d['construct_crystal']['ligand_id_type'],d['construct_crystal']['ligand_name'])

        if ligand and 'ligand_activity' in d['construct_crystal']:
            role_slug = slugify(d['construct_crystal']['ligand_activity'])
            try:
                lr, created = LigandRole.objects.get_or_create(slug=role_slug,
                defaults={'name': d['construct_crystal']['ligand_activity']})
            except IntegrityError:
                lr = LigandRole.objects.get(slug=role_slug)

        ligand_c = CrystallizationLigandConc()
        ligand_c.construct_crystallization = c
        ligand_c.ligand = ligand
        ligand_c.ligand_role = lr
        if 'ligand_conc' in d['construct_crystal']:
            ligand_c.ligand_conc = d['construct_crystal']['ligand_conc']
        if 'ligand_conc_unit' in d['construct_crystal']:
            ligand_c.ligand_conc_unit = d['construct_crystal']['ligand_conc_unit']
        ligand_c.save()

        c.ligands.add(ligand_c)

        construct.crystallization = c

    construct.save()