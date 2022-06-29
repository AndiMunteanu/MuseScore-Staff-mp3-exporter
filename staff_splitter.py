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

        if measure_parent.tag == "Measure":
            output_dictionary["tempo_elements"].append(temp_elem)
            output_dictionary["duration_passed"].append(
                _get_passed_duration(temp_elem))
            output_dictionary["measure_indices"].append(
                mscore_xml_object.Score.Staff[0].index(measure_parent))
            output_dictionary["location_inside_measure"].append(
                temp_elem.getparent().index(temp_elem))

    return output_dictionary

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

def _get_fraction_string(duration):
    eps = 1e-8
    fact = 1
    
    while True:
        if abs(int(duration) - duration) < eps:
            return f"{int(duration)}/{fact}"
        
        fact = fact * 2
        duration = duration * 2
    
def _generate_rest_xml(duration_list):
    rest_list = []
    for duration in duration_list:
        if duration.startswith("dot_"):
            xml_string = f"<Rest><dots>1</dots><durationType>{duration[4:]}</durationType></Rest>"
        else:
            xml_string = f"<Rest><durationType>{duration}</durationType></Rest>"
        rest_list.append(objectify.XML(xml_string))

    return rest_list

def _generate_note_xml(duration_list, note_template):
    note_list = []
    n_notes = len(duration_list)

    dots_element = note_template.find('dots')
    if dots_element is not None:
        note_template.remove(dots_element)
        
    prev_duration = 0

    for i, duration in enumerate(duration_list):
        new_note = deepcopy(note_template)
        if duration.startswith("dot_"):
            new_note.insert(0, objectify.XML("<dots>1</dots>")) 
            new_note.durationType._setText(duration[4:])
        else:
            new_note.durationType._setText(duration)

        duration_int = NOTES_DURATIONS_DICT[duration]
        spanner_start = objectify.XML(f"""
        <Spanner type="Tie">
            <Tie></Tie>
            <next>
                <location>
                    <fractions>{_get_fraction_string(duration_int)}</fractions>
                </location>
            </next>
        </Spanner>    
        """)

        spanner_stop = objectify.XML(f"""
        <Spanner type="Tie">
            <prev>
                <location>
                    <fractions>-{_get_fraction_string(prev_duration)}</fractions>
                </location>
            </prev>
        </Spanner>    
        """)

        prev_duration = duration_int

        if i > 0:
            new_note.Note.insert(0, spanner_stop)
        if i < n_notes - 1:
            new_note.Note.insert(0, spanner_start)

        note_list.append(new_note)

    return note_list 

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

        current_duration += duration

        if current_duration > passed_duration:
            durations_before = _get_note_combination(passed_duration + duration - current_duration)
            parent_elem = note_elem.getparent()
            index_elem = parent_elem.index(note_elem)
            parent_elem.remove(note_elem) 

            durations_after = _get_note_combination(current_duration - passed_duration)
            if note_elem.tag == "Rest":
                elements_after = _generate_rest_xml(durations_after)  
                elements_before = _generate_rest_xml(durations_before)
            else:
                elements_after = _generate_note_xml(durations_after, note_elem)
                elements_before = _generate_note_xml(durations_before, note_elem)

            stop_note = elements_after[0]

            for elem in elements_after[::-1]:
                parent_elem.insert(index_elem, elem)

            for elem in elements_before[::-1]:
                parent_elem.insert(index_elem, elem)
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
    output_dictionary["repeat_elements"] = []

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

    if hasattr(mscx_obj.Score.Staff[0], 'VBox'):
        vbox_element = mscx_obj.Score.Staff[0].VBox
    else:
        vbox_element = None

    mscx_obj.Score.Order = []

    for i in range(n_parts):
        if hasattr(parts[i].Instrument, "longName"):
            output_dictionary["parts"].append(parts[i].Instrument.longName.text)
        else:
            output_dictionary["parts"].append(f"Instrument_{i}")
        
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
