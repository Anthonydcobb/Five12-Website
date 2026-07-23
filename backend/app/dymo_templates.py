"""Pure logic for DYMO label templates: extract the named text objects
(the mail-merge variables) from a .dymo label's XML. No Flask/DB deps."""
import xml.etree.ElementTree as ET


def extract_variables(label_xml):
    try:
        root = ET.fromstring(label_xml)
    except ET.ParseError as exc:
        raise ValueError('invalid label XML') from exc
    seen, out = set(), []
    # Text objects across DYMO's format generations end in 'TextObject'
    # (TextObject, StyledTextObject, ...). Only those carry merge variables.
    for obj in root.iter():
        if not obj.tag.endswith('TextObject'):
            continue
        name_el = obj.find('Name')
        name = (name_el.text or '').strip() if name_el is not None else ''
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out
