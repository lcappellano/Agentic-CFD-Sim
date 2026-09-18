# CAD notes

- Import STEP directly in metres (`Geometry.OCCTargetUnit=M`); importing in mm and scaling by 0.001 in OCC produced wrong mass properties. Face tags are stable between the mm display import and the metre extraction import.
- Port loops fitted from the display model are unoriented; the extractor orients normals by inside/outside probes on the fluid volume. (`extract_passage.py`)
- Capping the selected port edges with plane faces and fragmenting an enclosing box with solid + caps gives the passage as the enclosed void carrying all caps; this reproduced the manifold extraction (solid 1.39713e-5 m³, 196 interface faces) without the old axis-aligned constraint.
- A distance/threshold field alone does not keep the wall size across a 1 mm gap; a `refinement_boxes` override in the mesh spec does. Five edges across a gap are not five boundary layers.
- Mesh profile sizes are per inlet hydraulic diameter so the same profile fits parts of different scale.
