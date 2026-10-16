# Wofi Overlay: wofi 1.5.3 패치 3가지
# 1) hover select — 마우스를 움직이면 해당 항목을 선택
#    (이유: 클릭해야만 선택되고 마우스 이동으로는 선택되지 않음. fuzzel 처럼 hover 만으로 선택 강조)
#    (주의: 클릭이 아닌 '실제 마우스 이동'(motion)에만 반응 — 목록이 갱신되며 커서 아래로 항목이 밀려와도 선택이 튀지 않음)
# 2) 시작 시 포커스를 검색창에 둠 — 기본은 목록 첫 항목에 포커스를 줘서 text-input(IME)이 꺼진 채 시작하고,
#    첫 키가 도착한 뒤에야 검색창으로 포커스를 넘겨 첫 글자가 IME 를 거치지 않고 영어로 입력되던 문제 수정
#    (방향키 이동은 "검색창 포커스면 select_idx(1)" 로 이미 짜여 있어 영향 없음)
# 3) 서피스 크기 보정 — 레이어 서피스/창 크기를 요청할 때 CSS 의 테두리+패딩만큼(WOFI_EXTRA) 더해서 요청
#    (이유: wofi 는 width/height 를 그대로 요청하지만 GTK 는 #outer-box 의 테두리+패딩 양쪽 합(wofi.nix 의 extra, 현재 22px) 만큼
#           더 큰 창을 요구함 → 입력/포커스마다 "요청 크기로 줄었다가 GTK 가 다시 키우는" 1프레임 흔들림 발생)
#    (주의: WOFI_EXTRA 는 wofi.nix 의 extra = 2*(borderPx+paddingPx) 와 반드시 일치해야 함)
_final: prev: {
  wofi = prev.wofi.overrideAttrs (old: {
    postPatch =
      (old.postPatch or "")
      + ''
        substituteInPlace src/wofi.c \
          --replace-fail 'static uint64_t width, height;' \
'#define WOFI_EXTRA 22
static uint64_t width, height;' \
          --replace-fail 'zwlr_layer_surface_v1_set_size(surface, width, height);' \
                         'zwlr_layer_surface_v1_set_size(surface, width + WOFI_EXTRA, height + WOFI_EXTRA);' \
          --replace-fail 'zwlr_layer_surface_v1_set_size(wlr_surface, width, height);' \
                         'zwlr_layer_surface_v1_set_size(wlr_surface, width + WOFI_EXTRA, height + WOFI_EXTRA);' \
          --replace-fail 'gtk_window_resize(GTK_WINDOW(window), width, height);' \
                         'gtk_window_resize(GTK_WINDOW(window), width + WOFI_EXTRA, height + WOFI_EXTRA);' \
          --replace-fail 'gtk_window_set_default_size(GTK_WINDOW(window), width, height);' \
                         'gtk_window_set_default_size(GTK_WINDOW(window), width + WOFI_EXTRA, height + WOFI_EXTRA);' \
          --replace-fail '		gtk_flow_box_select_child(GTK_FLOW_BOX(inner_box), child);
		gtk_widget_grab_focus(GTK_WIDGET(child));' \
'		gtk_flow_box_select_child(GTK_FLOW_BOX(inner_box), child);
		gtk_entry_grab_focus_without_selecting(GTK_ENTRY(entry));' \
          --replace-fail 'static gboolean _insert_widget(gpointer data) {' \
'static gboolean hover_select(GtkWidget* widget, GdkEventMotion* event, gpointer data) {
	(void) event;
	(void) data;
	/* 항목(GtkFlowBoxChild)은 자체 GdkWindow 가 없어 motion 이벤트가 오지 않으므로
	   최상위 창에서 받아 포인터 위치로 항목을 찾는다 */
	GdkSeat* seat = gdk_display_get_default_seat(gdk_display_get_default());
	GdkWindow* gdk_win = gtk_widget_get_window(widget);
	if(seat == NULL || gdk_win == NULL) {
		return FALSE;
	}
	gint wx, wy, bx, by;
	gdk_window_get_device_position(gdk_win, gdk_seat_get_pointer(seat), &wx, &wy, NULL);
	if(!gtk_widget_translate_coordinates(widget, inner_box, wx, wy, &bx, &by)) {
		return FALSE;
	}
	GtkFlowBoxChild* hovered = gtk_flow_box_get_child_at_pos(GTK_FLOW_BOX(inner_box), bx, by);
	if(hovered != NULL && !gtk_flow_box_child_is_selected(hovered)) {
		user_moved = true;
		gtk_flow_box_select_child(GTK_FLOW_BOX(inner_box), hovered);
	}
	return FALSE;
}

static gboolean _insert_widget(gpointer data) {' \
          --replace-fail 'g_signal_connect(window, "key-press-event", G_CALLBACK(key_press), NULL);' \
'g_signal_connect(window, "key-press-event", G_CALLBACK(key_press), NULL);
	gtk_widget_add_events(window, GDK_POINTER_MOTION_MASK);
	g_signal_connect(window, "motion-notify-event", G_CALLBACK(hover_select), NULL);'
      '';
  });
}
