from lxml import etree, objectify
from copy import deepcopy
import base64

from sympy import true

INF = 10000000
NOTES_DURATIONS_DICT = {
    "whole": 1,
    "half": 1/2,
    "quarter": 1/4,
    "eighth": 1/8,
    "16th": 1/16,
    "32nd": 1/32,
    "64th": 1/64,
    "128th": 1/128,
    "256th": 1/256,
    "512th": 1/512,
    "1024th": 1/1024
}
for key, value in list(NOTES_DURATIONS_DICT.items()):
    NOTES_DURATIONS_DICT["dot_" + key] = value * 3/2
NOTE_DURATION_TUPLES = [(key, value)
                        for key, value in NOTES_DURATIONS_DICT.items()]
NOTE_DURATION_TUPLES.sort(key=lambda x: x[1])
NOTE_DURATIONS = [note[1] for note in NOTE_DURATION_TUPLES]
N_NOTE_TYPES = len(NOTE_DURATIONS)
MIN_DURATION = 1024


def _get_passed_duration(tempo_position):
    total_duration = 0

    sibling = tempo_position.getprevious()
    while sibling is not None:
        if sibling.tag in ["Rest", "Chord"]:
            duration_string = sibling.durationType.text
            if duration_string == "measure":
                fraction_elem = [int(x)
                                 for x in sibling.duration.text.split("/")]
                duration = fraction_elem[0] / fraction_elem[1]
            else:
                duration = NOTES_DURATIONS_DICT[duration_string]

            if hasattr(sibling, 'dots') and sibling.dots.text == "1":
                duration = duration * 3 / 2

            total_duration += duration

        sibling = sibling.getprevious()

    return total_duration


def _get_tempo_elements(mscore_xml_object):
    output_dictionary = dict()
    tempo_tag_names = ["Tempo", "Spanner"]
    search_string = " or ".join(
        ["self::" + tag_name for tag_name in tempo_tag_names])
    output_dictionary["tempo_elements"] = []
    candidates = mscore_xml_object.Score.Staff[0].xpath(
        f".//*[{search_string}]")
    output_dictionary["measure_indices"] = []
    output_dictionary["location_inside_measure"] = []
    output_dictionary["duration_passed"] = []

    for temp_elem in candidates:
        measure_parent = temp_elem.getparent().getparent()

        print(_get_passed_duration(temp_elem))
        print(etree.tostring(temp_elem))
        print(measure_parent.tag)
        if measure_parent.tag == "Measure":
            output_dictionary["tempo_elements"].append(temp_elem)
            output_dictionary["duration_passed"].append(
                _get_passed_duration(temp_elem))
            output_dictionary["measure_indices"].append(
                mscore_xml_object.Score.Staff[0].index(measure_parent))
            output_dictionary["location_inside_measure"].append(
                temp_elem.getparent().index(temp_elem))

    return output_dictionary


def _get_duration_combination(duration):
    note_duration_tuples = [(key, value)
                            for key, value in NOTES_DURATIONS_DICT.items()]
    # make sure to have duration decreasingly sorted
    note_duration_tuples.sort(key=lambda x: x[1], reverse=True)

    combination = []
    current_duration = duration

    for duration_tuple in note_duration_tuples:
        print(duration_tuple[0])
        note_duration = duration_tuple[1]

        if note_duration * 3/2 < current_duration:
            n_notes = current_duration // (note_duration * 3/2)
            combination.append((duration_tuple[0], n_notes, True))
            current_duration -= n_notes * note_duration * 3/2

        if note_duration < current_duration:
            n_notes = current_duration // note_duration
            combination.append((duration_tuple[0], n_notes, False))
            current_duration -= n_notes * note_duration

        if current_duration == 0:
            break

    print("curent_duration", current_duration)
    return combination

def _get_note_combination(interval):
    # DP approach works only with integers, thus the intervals must be converted to whole numbers
    int_interval = int(interval * MIN_DURATION * 2)
    note_durations = [int(note * MIN_DURATION * 2) for note in NOTE_DURATIONS]
    note_durations.insert(0, 0)

    M = [0]*(int_interval+1)
    S = [0]*(int_interval+1)

    for j in range(1, int_interval+1):
        minimum = INF
        note = 0

        for i in range(1, N_NOTE_TYPES+1):
            if(j >= note_durations[i]):
                minimum = min(minimum, 1+M[j-note_durations[i]])
                note = i
        M[j] = minimum
        S[j] = note 

    l = int_interval
    note_combination = []
    while(l > 0):
        note_combination.append(NOTE_DURATION_TUPLES[S[l]-1][0])
        l = l-note_durations[S[l]]

    return note_combination

def _generate_rest_xml(duration_list):
    rest_list = []
    for duration in duration_list:
        if duration.startswith("dot_"):
            xml_string = f"<Rest><dots>1</dots><durationType>{duration[4:]}</durationType></Rest>"
        else:
            xml_string = f"<Rest><durationType>{duration}</durationType></Rest>"
        rest_list.append(objectify.XML(xml_string))
        
    return rest_list


def _get_note_for_tempo(measure_elem, passed_duration):
    chords_rests_elems = measure_elem.xpath(".//*[self::Chord or self::Rest]")

    current_duration = 0

    for note_elem in chords_rests_elems:
        if current_duration == passed_duration:
            stop_note = note_elem
            break

        duration_string = note_elem.durationType.text

        if duration_string == "measure":
            fraction_elem = [int(x)
                             for x in note_elem.duration.text.split("/")]
            duration = fraction_elem[0] / fraction_elem[1]
        else:
            duration = NOTES_DURATIONS_DICT[duration_string]

        if hasattr(note_elem, 'dots') and note_elem.dots.text == "1":
            duration = duration * 3 / 2

        print(current_duration, duration)
        current_duration += duration
        print(current_duration, passed_duration)

        if current_duration > passed_duration:
            # print(_get_duration_combination(
                # passed_duration + duration - current_duration))
            durations_before = _get_note_combination(passed_duration + duration - current_duration)
            elements_before = _generate_rest_xml(durations_before)
            parent_elem = note_elem.getparent()
            index_elem = parent_elem.index(note_elem)
            parent_elem.remove(note_elem) 


            durations_after = _get_note_combination(current_duration - passed_duration)
            elements_after = _generate_rest_xml(durations_after)
            stop_note = elements_after[0]

            for elem in elements_after[::-1]:
                parent_elem.insert(index_elem, elem)

            for elem in elements_before[::-1]:
                parent_elem.insert(index_elem, elem)
            
            
            # print(current_duration - passed_duration)
            print(current_duration - passed_duration)
            print("right", current_duration - passed_duration, "left",
                  duration - current_duration + passed_duration, duration)
            # note_elem.addnext(objectify.XML("<test>a mres</test>"))
            break
        
    return stop_note


def _get_repeat_elements(mscore_xml_object):
    output_dictionary = dict()
    repeat_tag_names = ["Marker", "startRepeat", "endRepeat", "Jump"]
    search_string = " or ".join(
        ["self::" + tag_name for tag_name in repeat_tag_names])
    candidates = mscore_xml_object.Score.Staff[0].xpath(
        f".//*[{search_string}]")
    output_dictionary["measure_indices"] = []
    output_dictionary["location_inside_measure"] = []

    for repeat_elem in candidates:
        measure_parent = repeat_elem.getparent()

        if measure_parent.tag == "Measure":
            output_dictionary["repeat_elements"].append(repeat_elem)
            output_dictionary["measure_indices"].append(
                mscore_xml_object.Score.Staff[0].index(measure_parent))
            output_dictionary["location_inside_measure"].append(
                measure_parent.index(repeat_elem))

    return output_dictionary


def generate_parts(input_filename):
    mscx_obj = objectify.parse(input_filename).getroot()
    output_dictionary = {
        "parts": [],
        "partsBin": []
    }

    mscx_obj.Score.metaTag = objectify.StringElement(
        "metaTag", name="partName")

    parts = deepcopy(mscx_obj.Score.Part[:])
    staffs = deepcopy(mscx_obj.Score.Staff[:])
    n_parts = len(parts)
    repeat_elements_dict = _get_repeat_elements(mscore_xml_object=mscx_obj)
    tempo_elements_dict = _get_tempo_elements(mscore_xml_object=mscx_obj)

    print("--")
    if hasattr(mscx_obj.Score.Staff[0], 'VBox'):
        vbox_element = mscx_obj.Score.Staff[0].VBox
    else:
        vbox_element = None

    mscx_obj.Score.Order = []

    for i in range(n_parts):
        output_dictionary["parts"].append(parts[i].Instrument.longName.text)
        mscx_obj.Score.metaTag._setText(parts[i].trackName.text)
        mscx_obj.Score.Staff = [staffs[i]]
        mscx_obj.Score.Staff[0].attrib["id"] = "1"
        mscx_obj.Score.Part = [parts[i]]
        mscx_obj.Score.Part[0].Staff.attrib["id"] = "1"

        if i > 0:
            if vbox_element is not None:
                mscx_obj.Score.Staff[0].insert(0, vbox_element)

            staff_children = mscx_obj.Score.Staff[0].getchildren()
            for j, measure_index in enumerate(tempo_elements_dict["measure_indices"]):
                # staff_children[measure_index].voice.insert(tempo_elements_dict["location_inside_measure"][j],
                                                        #    tempo_elements_dict["tempo_elements"][j])

                note_element = _get_note_for_tempo(
                    staff_children[measure_index], tempo_elements_dict["duration_passed"][j])
                note_element.addprevious(tempo_elements_dict["tempo_elements"][j])

            for j, measure_index in enumerate(repeat_elements_dict["measure_indices"]):
                staff_children[measure_index].insert(repeat_elements_dict["location_inside_measure"][j],
                                                     repeat_elements_dict["repeat_elements"][j])

        mscx_etree = etree.ElementTree(mscx_obj)
        output_dictionary["partsBin"].append(
            base64.b64encode(etree.tostring(mscx_etree, pretty_print=True))
        )

    return output_dictionary
