# Project Plans

Project Plans is a local-first PyQt6 desktop application for building and reviewing week-based project timelines. Plans are saved as portable JSON files and can be exported as images, PDF, Markdown, or CSV.

## Capabilities

- Plan across ISO weeks and multiple years, with compact week and duration labels.
- Organize the timeline into sections, deliverable rows, and visual dividers.
- Add tasks, milestones, deadlines, events, connectors, and free-positioned text boxes.
- Select, move, resize, duplicate, delete, reorder, and style plan content with undo/redo support.
- Create finish-to-start dependencies by dragging between object ports or by editing predecessors in the Details panel.
- Optionally push successors later when predecessors move, and detect schedule conflicts, missing references, and dependency cycles.
- Assign colour-coded subjects and filter the canvas from the subject legend.
- Group work across rows into initiatives and display initiative rollups.
- Search titles, notes, scope, and risks; inspect edit history and jump to an earlier change.
- Review the plan in a structured table or quarter-by-quarter Period Overview.
- Switch among Edit, Navigation, Presentation, and Canvas Full Screen modes, including light and dark themes.
- Arrange overlapping scheduled objects in vertical lanes, with configurable milestone/event symbol-overlap tolerance.
- Export selected quarters to PNG or PDF, copy them to the clipboard, and automatically refresh a PNG whenever the plan is saved.
- Export scope to Markdown and risks to semicolon-delimited CSV.

The application is fully local and offline. It does not require an account, cloud service, or network access.

## Requirements

- Python 3.10 or newer
- PyQt6

Install the dependencies:

```bash
python -m pip install -r requirements.txt
```

## Run

```bash
python app.pyw
```

Alternatively:

```bash
python -m projectplans
```

On Windows, use `pythonw app.pyw` to run without a console window.

## Getting Started

1. Use **Add > Add Section** to create a planning section.
2. Add deliverables to the section to create timeline rows.
3. Choose an object from the **Add** toolbar menu or **Insert** menu, then drag on the canvas to place it. Dragging an empty planning row also creates a task.
4. Double-click text or press **F2** to rename an item. Open **Details** (`Ctrl+Shift+D`) to edit dates, style, scope, risks, notes, subjects, and dependencies.
5. Save the plan as JSON with `Ctrl+S`, or click the **Unsaved** indicator.

The built-in **Help > How to Use** guide covers the complete workflow, and **Help > Shortcuts** lists the active keyboard shortcuts.

## Working with the Timeline

### Interaction modes

- **Edit** allows creation and changes.
- **Navigation** supports panning, zooming, and inspection without moving objects.
- **Presentation** provides a clean, read-only view and hides editing affordances.
- **Canvas Full Screen** hides application chrome and provides a read-only canvas for presentation. Press `Esc` or `F11` to exit.

Use **View > Interaction > Snap Weeks and Rows** to control whether creation, movement, resizing, symbols, and connectors align to the planning grid. Hold **Space** or drag with the right mouse button to pan while in Edit mode.
In Edit mode, **View > Display > Show Position Guidance** displays the week and row beside the pointer; it is enabled by default.

### Selection and editing

- Click to select; `Ctrl`/`Cmd`-click toggles an item in a multi-selection.
- `Ctrl`/`Cmd`-drag on empty canvas creates a selection marquee.
- Drag a selected group to move it together; drag task edge grips to resize.
- `Ctrl+D` duplicates, `Delete` removes, and `Ctrl+Z` / `Ctrl+Y` undo and redo.
- Duplicates retain their content and appearance but do not inherit dependencies, connectors, or textbox links.
- Arrow keys nudge the selection by a week or row. `Shift`+Arrow resizes supported objects or adjusts a free connector target.
- Drag the row-label divider to change the label-column width.
- Right-click the canvas, an object, or a row label for contextual insert, convert, ordering, focus, collapse, indent, and row-management actions.
- Use **View > Overlap Layout** to set the allowed symbol overlap for milestones and events. Labels remain protected and activities use strict body overlap rules.

Rich-text fields support `Ctrl+B`, `Ctrl+I`, and `Ctrl+U`. Use `Alt+Shift+S` for strikethrough and `Ctrl+]` / `Ctrl+[` to change selected text size.

### Insert shortcuts

| Key | Object |
| --- | --- |
| `B` | Task |
| `M` | Milestone |
| `D` | Deadline |
| `C` | Event |
| `A` or `F` | Connector |
| `X` | Text box |

Press `Esc` to cancel placement. Connectors are created by dragging from one object edge to another, or by dragging across empty grid space for a free connector. A text box can be anchored by dragging from its edge to another object.

## Dependencies and Scheduling

Dependencies are explicit finish-to-start predecessor relationships, separate from ordinary visual connectors.

- Hover a schedulable object to reveal its left and right **+** ports.
- Drag the left port to assign a predecessor, or the right port to assign a successor. Text boxes expose four link handles and can connect to multiple objects.
- A cyan receptor accepts the relationship; red feedback indicates a duplicate, cycle, or otherwise invalid link.
- Select dependency paths individually or as a group and press `Delete` to remove them.
- Manage the same relationships from **Details > Dependencies**.
- Enable **View > Planning Behavior > Auto-reschedule Dependencies** to push successors later when needed. Their duration is preserved; this option does not pull work earlier.

The **!** button reports dependency conflicts, missing predecessors, and cycles. Issues can be opened on the canvas or ignored individually.

## Organizing and Reviewing Plans

- **Subjects:** create and manage colour-coded subjects from **Project**, assign them in Details, and use the legend below the canvas to filter the view.
- **Initiatives:** create an initiative, select related objects, and choose **Project > Link Selection to Initiative**. Enable **Initiative Rollup** for a higher-level view.
- **Rows:** rename, reorder, move, indent, focus, collapse, or expand sections and deliverables from their context menus. Dividers separate major areas.
- **Search:** press `Ctrl+F` to search object titles, notes, scope, and risks. Matching objects are highlighted and can be stepped through.
- **Plan Table:** shows type, title, section, subject, dates, duration, predecessors, and initiative; double-click a row to reveal its object.
- **Period Overview:** summarizes the objects and milestones overlapping a selected quarter.
- **History:** use **Edit > History** to jump to any point in the current undo stack.
- **Display:** highlight the current week, show position guidance, flag tasks with missing scope, hide text boxes, toggle dark mode, or show/hide Details.

Navigation tools include zoom in/out/reset, Zoom to Selection, Zoom to Fit, and Today. `Ctrl`+mouse wheel also zooms.

## Exporting

From the **Export** menu:

- **Planning as PNG/PDF:** select the quarter range to render.
- **Copy Image to Clipboard:** copy a selected planning range for pasting into another application.
- **Scope as Markdown:** choose rows and export scope, dependencies, deadlines, anchored text, and an object-reference appendix.
- **Risks as CSV:** export semicolon-delimited risks. A risk line may use `risk;probability;impact`, with `h`, `m`, or `l` values.
- **Automatic PNG Export:** choose a destination and the number of additional quarters to include from the current quarter. The file is overwritten after each successful save.

Export dialogs default to the operating system's Downloads folder when available.

## Persistence

Project files use schema-versioned JSON. A plan stores:

- base year, classification label and size;
- sections, deliverables, collapse state, objects, subjects, and initiatives;
- predecessor relationships, ignored planning issues, and the auto-reschedule setting;
- zoom, scroll position, label-column width, and automatic-export settings.

User-level Qt settings store the last and recent files, window geometry and dock state, the selected Details tab, theme, last zoom, and display preferences. Saves use Qt's safe-file mechanism so the existing project is replaced only after the new content is written successfully.

## Limitations

- Project Plans is a single-user desktop application; it has no collaboration or cloud synchronization.
- Timeline image and PDF exports use quarter-based ranges.
- Dependencies and connectors require supported canvas-object targets; invalid targets are rejected.
- Edit history belongs to the current application session and is not stored in the project file.

## License

Project Plans is licensed under the GNU General Public License v3.0 or later. See [LICENSE](LICENSE).
