extends Control
## Sample scene: draws a card and prints it, or prints typed text.

@onready var bridge: Node = $PrintBridge
@onready var card: Control = $VBox/Card
@onready var text_edit: LineEdit = $VBox/TextEdit
@onready var status: Label = $VBox/Status
@onready var mode_option: OptionButton = $VBox/Buttons/Mode


func _ready() -> void:
	bridge.print_finished.connect(_on_print_finished)
	$VBox/Buttons/PrintCard.pressed.connect(_on_print_card)
	$VBox/Buttons/PrintText.pressed.connect(_on_print_text)
	mode_option.item_selected.connect(func(i): bridge.mode = i)
	status.text = "mode: SPOOL → run `phomemo serve --spool %s`" % bridge.spool_dir


func _on_print_card() -> void:
	# Render the Card subtree into its own image via a SubViewport-free capture:
	# grab the whole screen and crop to the card's rect.
	await RenderingServer.frame_post_draw
	var full := get_viewport().get_texture().get_image()
	var rect := Rect2i(card.get_global_rect())
	bridge.print_image(full.get_region(rect))
	status.text = "printing card..."


func _on_print_text() -> void:
	if text_edit.text.strip_edges().is_empty():
		return
	bridge.print_text(text_edit.text)
	status.text = "printing text..."


func _on_print_finished(ok: bool, message: String) -> void:
	status.text = ("OK: " if ok else "ERROR: ") + message
