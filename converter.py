# the MuseScore documentation lacks a lot of details
# if you want more about creating separate score parts, look over some files like
# 'converter/internal/compat/backendapi.cpp'
# 'converter/internal/convertercontroller.cpp'
# 'converter/convertermodule.cpp'
# 'appshell/appshell.h'
# 'appshell/commandlinecontroller.cpp


# The pipeline that I am intersted in:
# INPUT: mscz/mscx file that contains a choir sheet with each voice on a different
#   staff (I prefer using mscx and not musicxml, as the latter seem to have some 
#   limitations like lack for fermata duration support)
# OUTPUT: four mp3 files where each voice will be highlighted using a different 
#   instrument (my go-to is the clarinet)
# STEPS:
#   1. Split the initial musescore file into parts using the CLI argument `--score-parts`
#   2. The results will be stored in an JSON filed that will contain the data 
#   for each mscz file that contains the part (WARNING: the data is encoded in base64)
#   3. For each part, generate a mp3 file with the original voices. This voices
#   will be used as background. For this I will use the musescore CLI argument
#   (using the -o parameter)
#   4. Change the instrument for each part. The current approach will be to
#   make use of the xml structure of the files and manually change the instruments.
#   The informations for the instruments will be extracted from `instruments.xml`.
#   Some / most of the instruments require applying some transposition, that will
#   be made using the `--score-transpose` parameter for musescore CLI.
#   5. Generate the lead mp3 voices.
#   6. Generate the final four mp3 files that will contain a merge between a
#   lead part and three background ones. The volume of the background parts
#   will be intentionally lowered.
# PURPOSE: I find this kind of files to be helpful for those who want to learn
#   a part of a melody.

import subprocess
import sys
import os
import json
import base64
from lxml import etree, objectify
from time import strftime
from copy import deepcopy
import xmltodict

musescore = "org.musescore.MuseScore"

def get_desired_instrument_json(instrument_name = "clarinet"):
    etree_xml = etree.parse("instruments.xml")
    exact_search_result = etree_xml.xpath(f'//Instrument[@id="{instrument_name}"]')

    if len(exact_search_result) == 0:
        regex_search_result = etree_xml.xpath(f'(//Instrument[contains(@id, "{instrument_name}")])[1]')
        instrument_obj = regex_search_result[0]
    else:
        instrument_obj = exact_search_result[0]

    json_obj = xmltodict.parse(etree.tostring(instrument_obj).decode())
    json_obj = json_obj["Instrument"]

    if 'aPitchRange' in json_obj:
        a_range = json_obj['aPitchRange'].split('-')
        json_obj['minPitchA'] = a_range[0]
        json_obj['maxPitchA'] = a_range[1]

    if 'pPitchRange' in json_obj:
        p_range = json_obj['pPitchRange'].split('-')
        json_obj['minPitchP'] = p_range[0]
        json_obj['maxPitchP'] = p_range[1]

    if 'instrumentId' not in json_obj:
        try:
            json_obj['instrumentId'] = json_obj['musicXMLid']
        except KeyError:
            json_obj['instrumentId'] = "voice.soprano"
            
    return json_obj

def change_instrument(input_filename, output_filename, desired_instrument = "clarinet"):
    # instead of adding the details from instrument.xml to parts
    # add the details from parts to the instrument and replace in the input mscx
    instrument_json = get_desired_instrument_json(instrument_name = desired_instrument)

    mscx_obj = objectify.parse(input_filename).getroot()
    mscx_obj.Score.Style.concertPitch = objectify.StringElement("concertPitch")
    mscx_obj.Score.Style.concertPitch._setText('1')

    for i in range(len(mscx_obj.Score.Part)):
        mscx_obj.Score.Part[i].Instrument.attrib["id"] = instrument_json["@id"] 
        
        for elem_child in mscx_obj.Score.Part[i].Instrument.getchildren():
            if elem_child.tag in instrument_json and elem_child.tag != "Channel":
                elem_child._setText(instrument_json[elem_child.tag])

        mscx_obj.Score.Part[i].Instrument.Channel.program.attrib["value"] = instrument_json["Channel"]["program"]["@value"]

    mscx_etree = etree.ElementTree(mscx_obj)
    mscx_etree.write(output_filename, pretty_print = True)

def generate_parts(input_filename):
    mscx_obj = objectify.parse(input_filename).getroot()
    output_dictionary = {
        "parts" : [],
        "partsBin" : []
    } 
    
    mscx_obj.Score.metaTag = objectify.StringElement("metaTag", name="partName")

    parts = deepcopy(mscx_obj.Score.Part[:])
    staffs = deepcopy(mscx_obj.Score.Staff[:])
    n_parts = len(parts)
    measure_indices = []
    tempo_elements = []
    tempo_placement = []
    vbox_element = mscx_obj.Score.Staff[0].VBox
    
    for x in mscx_obj.Score.Staff[0].findall(".//Tempo"):
        measure_parent = x.getparent().getparent()
        measure_index = mscx_obj.Score.Staff[0].index(measure_parent)
        tempo_index = x.getparent().index(x)
        measure_indices.append(measure_index)
        tempo_placement.append(tempo_index)
        tempo_elements.append(x)

    mscx_obj.Score.Order = [] 

    for i in range(n_parts):
        output_dictionary["parts"].append(parts[i].trackName.text)
        mscx_obj.Score.metaTag._setText(parts[i].trackName.text)
        mscx_obj.Score.Staff = [staffs[i]]
        mscx_obj.Score.Staff[0].attrib["id"] = "1"
        mscx_obj.Score.Part = [parts[i]]
        mscx_obj.Score.Part[0].Staff.attrib["id"] = "1"

        if i > 0:
            mscx_obj.Score.Staff[0].insert(0, vbox_element)

            staff_children = mscx_obj.Score.Staff[0].getchildren() 
            for j, measure_index in enumerate(measure_indices):
                staff_children[measure_index].voice.insert(tempo_placement[j], tempo_elements[j])

        mscx_etree = etree.ElementTree(mscx_obj)
        output_dictionary["partsBin"].append(
            base64.b64encode(etree.tostring(mscx_etree, pretty_print=True))
        )

    return output_dictionary

def generate_leading_audios(input_filename,
                            max_weight = 3, 
                            target_instrument = "clarinet",
                            verbose = True,
                            process_verbose = False):
    base_filename = os.path.basename(input_filename).split('.')[0]
    folder_path = os.path.dirname(input_filename)

    if not os.path.exists(os.path.join(folder_path, "parts")):
        os.mkdir(os.path.join(folder_path, "parts"))

    if not os.path.exists(os.path.join(folder_path, "parts", "mscz")):
        os.mkdir(os.path.join(folder_path, "parts", "mscz"))

    if not os.path.exists(os.path.join(folder_path, "parts", "mp3")):
        os.mkdir(os.path.join(folder_path, "parts", "mp3"))
        
    # 0. check if mscx file exists
    if os.path.basename(input_filename).split('.')[-1] == "mscz":
        if verbose: print(f"[{strftime('%H:%M:%S')}] Convert mscz to mscx")
        proc_output = subprocess.run([musescore, '-o', input_filename[:-1] + "x", input_filename],
                                     capture_output = True)
        if process_verbose: print(proc_output)
        input_filename = input_filename[:-1] + "x"

    # 1. split score
    if verbose: print(f"[{strftime('%H:%M:%S')}] Splitting score into parts")
    # splitter_process = subprocess.run([musescore, "--score-parts", file_path], \
                                    # capture_output = True)
    parts_dict = generate_parts(input_filename=input_filename)
    # parts_dict = json.loads(splitter_process.stdout.decode())
    part_names = parts_dict["parts"]
    parts_mscx_files = [os.path.join(folder_path, "parts", "mscz", f"{part_name}_background_{base_filename}.mscx") for part_name in part_names]
    instrument_mscx_files = [os.path.join(folder_path, "parts", "mscz", f"{part_name}_lead_{base_filename}.mscx") for part_name in part_names]
    background_mp3_names = [os.path.join(folder_path, "parts", "mp3", f"{part_name}_background_{base_filename}.mp3") for part_name in part_names]
    lead_mp3_names = [os.path.join(folder_path, "parts", "mp3", f"{part_name}_lead_{base_filename}.mp3") for part_name in part_names]

    for i, bkg_mp3_name in enumerate(background_mp3_names):
        # 2. generate a mscx for each part
        if verbose: print(f"[{strftime('%H:%M:%S')}] Generate mscx file for {part_names[i]}")
        with open(parts_mscx_files[i], "wb") as fout:
            fout.write(base64.b64decode(parts_dict['partsBin'][i]))
        # temp_mscx_file = parts_mscx_files[i][:-1] + 'x'
        # proc_output = subprocess.run([musescore, '-o', temp_mscx_file, parts_mscx_files[i]],
                                    #  capture_output = True)
        # if process_verbose: print(proc_output)

        # 3. generate bck mp3
        if verbose: print(f"[{strftime('%H:%M:%S')}] Generate background mp3 for {part_names[i]}")
        proc_output = subprocess.run([musescore, '-o', bkg_mp3_name, parts_mscx_files[i]],
                                     capture_output = True)
        if process_verbose: print(proc_output)

        # 4. convert to given instrument
        if verbose: print(f"[{strftime('%H:%M:%S')}] Change instrument for {part_names[i]}")
        change_instrument(parts_mscx_files[i], instrument_mscx_files[i], target_instrument)

        # 5. generate lead mp3
        if verbose: print(f"[{strftime('%H:%M:%S')}] Generate lead mp3 for {part_names[i]}")
        proc_output = subprocess.run([musescore, '-o', lead_mp3_names[i], instrument_mscx_files[i]],
                                     capture_output = True)
        if process_verbose: print(proc_output)

    # 6. Merge lead with background
    n_parts = len(part_names)

    for i in range(n_parts):
        if verbose: print(f"[{strftime('%H:%M:%S')}] Merge audio with lead for {part_names[i]}")
        ffmpeg_command = ['ffmpeg', '-y', '-i', lead_mp3_names[i]]
        final_name = os.path.join(folder_path, f"{part_names[i]}_{base_filename}.mp3")
        weights = [f'{max_weight}']
        
        for j in [x for x in range(n_parts) if x != i]:
            ffmpeg_command.append('-i')
            ffmpeg_command.append(background_mp3_names[j])
            weights.append(f'{max_weight-1}')

        amix_string = f'amix=inputs={n_parts}:duration=longest:dropout_transition=0:weights={" ".join(weights)}'

        ffmpeg_command.append('-filter_complex')
        ffmpeg_command.append(amix_string)
        ffmpeg_command.append(final_name)
        proc_output = subprocess.run(ffmpeg_command, capture_output = True)
        if process_verbose: print(proc_output)

if __name__ == "__main__":
    if len(sys.argv) <= 1:
        exit("nu sunt destule argumente")

    instrument_name = "clarinet"
    max_weight = 3
    if len(sys.argv) > 2:
        instrument_name = sys.argv[2]
    if len(sys.argv) > 3:
        max_weight = int(sys.argv[2])

    file_path = sys.argv[1]
    if not os.path.exists(file_path):
        exit(f"the path {file_path} cannot be found")

    generate_leading_audios(input_filename=file_path,
                            max_weight=max_weight,
                            process_verbose=False,
                            verbose=True)