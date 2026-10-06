extends Node
## Bridge from Godot to the `phomemo` CLI.
##
## Two modes:
##   SPOOL  (recommended for exhibits): writes a PNG/TXT into the spool folder
##          watched by `phomemo serve`. Returns immediately; the resident
##          process queues jobs and keeps one BLE connection, so rapid
##          requests never collide.
##   DIRECT: runs `phomemo print ...` per job via OS.execute() on a worker
##          Thread. Jobs are queued here so only one CLI runs at a time.

signal print_finished(ok: bool, message: String)

enum Mode { SPOOL, DIRECT }

@export var mode: Mode = Mode.SPOOL
## Absolute path to the CLI, e.g. /Users/you/Desktop/phomemo-print/.venv/bin/phomemo
@export var phomemo_path: String = ""
## Absolute spool folder (must match `phomemo serve --spool`). Empty = <project>/../spool
@export var spool_dir: String = ""
## Extra CLI args for DIRECT mode, e.g. ["--dither", "atkinson"]
@export var extra_args: PackedStringArray = []

var _counter := 0
var _jobs: Array = []          # DIRECT mode: pending arg lists
var _thread: Thread = null
var _tmp_files: Array = []


func _ready() -> void:
	if phomemo_path.is_empty():
		phomemo_path = ProjectSettings.globalize_path("res://").path_join("../.venv/bin/phomemo").simplify_path()
	if spool_dir.is_empty():
		spool_dir = ProjectSettings.globalize_path("res://").path_join("../spool").simplify_path()
	DirAccess.make_dir_recursive_absolute(spool_dir)


## Print an Image (any size; the CLI scales it to 384px wide).
func print_image(img: Image) -> void:
	var name := _next_name("png")
	if mode == Mode.SPOOL:
		_spool_write(name, func(path): return img.save_png(path))
	else:
		var path := OS.get_temp_dir().path_join(name)
		if img.save_png(path) != OK:
			print_finished.emit(false, "save_png failed")
			return
		_tmp_files.append(path)
		_enqueue(["print", path] + Array(extra_args))


## Capture what the given viewport (default: this one) is showing and print it.
func print_viewport(vp: Viewport = null) -> void:
	if vp == null:
		vp = get_viewport()
	await RenderingServer.frame_post_draw
	print_image(vp.get_texture().get_image())


## Print text (Japanese OK, uses Hiragino on macOS).
func print_text(text: String) -> void:
	if mode == Mode.SPOOL:
		_spool_write(_next_name("txt"), func(path):
			var f := FileAccess.open(path, FileAccess.WRITE)
			if f == null:
				return FileAccess.get_open_error()
			f.store_string(text)
			f.close()
			return OK)
	else:
		_enqueue(["print", "--text", text] + Array(extra_args))


func is_busy() -> bool:
	return _thread != null or not _jobs.is_empty()


# ------------------------------------------------------------------ spool

func _next_name(ext: String) -> String:
	_counter += 1
	return "%d_%03d.%s" % [int(Time.get_unix_time_from_system() * 1000.0), _counter, ext]


## Write under a dotfile name, then rename, so `phomemo serve` never sees a
## half-written file.
func _spool_write(name: String, writer: Callable) -> void:
	var tmp := spool_dir.path_join("." + name + ".tmp")
	var final := spool_dir.path_join(name)
	var err: int = writer.call(tmp)
	if err == OK:
		err = DirAccess.rename_absolute(tmp, final)
	if err == OK:
		print_finished.emit(true, "spooled " + name)
	else:
		print_finished.emit(false, "spool write failed: %s" % error_string(err))


# ------------------------------------------------------------------ direct

func _enqueue(args: Array) -> void:
	_jobs.append(args)
	_pump()


func _pump() -> void:
	if _thread != null or _jobs.is_empty():
		return
	var args: Array = _jobs.pop_front()
	_thread = Thread.new()
	_thread.start(_run_cli.bind(args))


func _run_cli(args: Array) -> void:
	var output: Array = []
	var code := OS.execute(phomemo_path, PackedStringArray(args), output, true)
	call_deferred("_on_cli_done", code, "\n".join(output))


func _on_cli_done(code: int, output: String) -> void:
	_thread.wait_to_finish()
	_thread = null
	# CLI exit codes: 0 ok, 1 error, 2 printer not found, 3 bad input
	print_finished.emit(code == 0, output.strip_edges())
	if _jobs.is_empty():
		for p in _tmp_files:
			DirAccess.remove_absolute(p)
		_tmp_files.clear()
	_pump()


func _exit_tree() -> void:
	if _thread != null:
		_thread.wait_to_finish()
