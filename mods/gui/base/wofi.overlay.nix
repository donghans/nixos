# Wofi Overlay: wofi 1.5.3 패치 6가지
# 1) hover select — 마우스를 움직이면 해당 항목을 선택
#    (이유: 클릭해야만 선택되고 마우스 이동으로는 선택되지 않음. fuzzel 처럼 hover 만으로 선택 강조)
#    (주의: 클릭이 아닌 '실제 마우스 이동'(motion)에만 반응 — 목록이 갱신되며 커서 아래로 항목이 밀려와도 선택이 튀지 않음)
# 2) 시작 시 포커스를 검색창에 둠 — 기본은 목록 첫 항목에 포커스를 줘서 text-input(IME)이 꺼진 채 시작하고,
#    첫 키가 도착한 뒤에야 검색창으로 포커스를 넘겨 첫 글자가 IME 를 거치지 않고 영어로 입력되던 문제 수정
#    (방향키 이동은 "검색창 포커스면 select_idx(1)" 로 이미 짜여 있어 영향 없음)
# 3) 방향키 이동을 "선택만 변경 + 포커스는 검색창 유지" 방식으로 변경 — 기본은 GTK 포커스를 목록 항목으로 옮겨
#    text-input(IME)이 꺼지므로, 방향키로 이동한 뒤 입력하면 첫 글자가 다시 영어로 입력됨
#    (단일 열 + 세로 방향일 때만 적용(Tab/Shift+Tab 은 끝에서 순환), 그 외는 기존 동작. 스크롤은 adjustment 로 직접 보정해 포커스 이동 불필요)
#    + Enter 가 항상 0번째 항목만 실행하던 것을 선택된 항목 실행으로 변경 (검색창 포커스 유지 시 hover/방향키 선택이 무시되므로)
# 4) 플레이스홀더 — GTK3 입력창은 포커스가 있으면 플레이스홀더를 숨기는데, 시작 시 검색창에 포커스를 두므로
#    입력창 위에 라벨을 겹쳐 "텍스트가 비어 있고 IME 조합(preedit) 중이 아닐 때" 항상 표시
#    (라벨은 CSS #placeholder 로 스타일링, 입력은 통과)
# 5) 검색 일치 글자 강조 — 검색어가 바뀔 때마다 각 항목 라벨에서 일치한 글자를 찾아 Pango 속성(색+굵게)으로 표시
#    (fuzzy: 연속 부분문자열 우선, 아니면 부분수열 / contains 계열: 부분문자열(multi 는 공백 토큰별). 한글은 UTF-8 바이트 오프셋으로 처리)
#    (색 WOFI_MATCH_* 는 fuzzel 시절 match 색 #cb4b16)
# 6) 서피스 크기 보정 — 레이어 서피스/창 크기를 요청할 때 CSS 의 테두리+패딩만큼(WOFI_EXTRA) 더해서 요청
#    (이유: wofi 는 width/height 를 그대로 요청하지만 GTK 는 #outer-box 의 테두리+패딩 양쪽 합(wofi.nix 의 extra, 현재 18px) 만큼
#           더 큰 창을 요구함 → 입력/포커스마다 "요청 크기로 줄었다가 GTK 가 다시 키우는" 1프레임 흔들림 발생)
#    (주의: WOFI_EXTRA 는 wofi.nix 의 extra = 2*(borderPx+paddingPx) 와 반드시 일치해야 함)
_final: prev: {
  wofi = prev.wofi.overrideAttrs (old: {
    postPatch =
      (old.postPatch or "")
      + ''
        substituteInPlace src/wofi.c \
          --replace-fail 'static uint64_t width, height;' \
'#define WOFI_EXTRA 18
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
          --replace-fail 'static void move_up(void) {
	user_moved = true;' \
'static void scroll_to_child(GtkWidget* child) {
	GtkAdjustment* adj = gtk_scrolled_window_get_vadjustment(GTK_SCROLLED_WINDOW(scroll));
	GtkWidget* wrapper = gtk_widget_get_parent(inner_box);
	gint x, y;
	if(adj == NULL || wrapper == NULL || !gtk_widget_translate_coordinates(child, wrapper, 0, 0, &x, &y)) {
		return;
	}
	gdouble h = gtk_widget_get_allocated_height(child);
	gdouble value = gtk_adjustment_get_value(adj);
	gdouble page = gtk_adjustment_get_page_size(adj);
	if(y < value) {
		gtk_adjustment_set_value(adj, y);
	} else if(y + h > value + page) {
		gtk_adjustment_set_value(adj, y + h - page);
	}
}

static void move_selection(gint delta, gboolean wrap) {
	GList* selected = gtk_flow_box_get_selected_children(GTK_FLOW_BOX(inner_box));
	gint idx = selected != NULL ? gtk_flow_box_child_get_index(selected->data) : -1;
	g_list_free(selected);
	GtkFlowBoxChild* target = NULL;
	for(gint next = idx + delta; next >= 0; next += delta) {
		GtkFlowBoxChild* candidate = gtk_flow_box_get_child_at_index(GTK_FLOW_BOX(inner_box), next);
		if(candidate == NULL) {
			break;
		}
		/* 필터로 숨겨진 항목은 건너뜀 */
		if(gtk_widget_get_visible(GTK_WIDGET(candidate))) {
			target = candidate;
			break;
		}
	}
	if(target == NULL && wrap) {
		/* Tab 처럼 끝에서 반대쪽 끝으로 순환: 보이는 항목 중 처음(delta>0) 또는 마지막(delta<0) */
		for(gint next = 0;; ++next) {
			GtkFlowBoxChild* candidate = gtk_flow_box_get_child_at_index(GTK_FLOW_BOX(inner_box), next);
			if(candidate == NULL) {
				break;
			}
			if(gtk_widget_get_visible(GTK_WIDGET(candidate))) {
				target = candidate;
				if(delta > 0) {
					break;
				}
			}
		}
	}
	if(target != NULL) {
		gtk_flow_box_select_child(GTK_FLOW_BOX(inner_box), target);
		scroll_to_child(GTK_WIDGET(target));
	}
}

static void move_up(void) {
	user_moved = true;
	if(columns == 1 && outer_orientation == GTK_ORIENTATION_VERTICAL) {
		move_selection(-1, FALSE);
		return;
	}' \
          --replace-fail 'static void move_down(void) {
	user_moved = true;' \
'static void move_down(void) {
	user_moved = true;
	if(columns == 1 && outer_orientation == GTK_ORIENTATION_VERTICAL) {
		move_selection(1, FALSE);
		return;
	}' \
          --replace-fail '	GtkFlowBoxChild* child = gtk_flow_box_get_child_at_index(GTK_FLOW_BOX(inner_box), 0);
	gboolean is_visible = gtk_widget_get_visible(GTK_WIDGET(child));' \
'	/* 검색창에 포커스가 있어도 방향키/hover 로 선택한 항목을 실행 (선택이 없거나 숨겨졌으면 0번째) */
	GtkFlowBoxChild* child = NULL;
	GList* selected_items = gtk_flow_box_get_selected_children(GTK_FLOW_BOX(inner_box));
	if(selected_items != NULL && gtk_widget_get_visible(GTK_WIDGET(selected_items->data))) {
		child = selected_items->data;
	}
	g_list_free(selected_items);
	if(child == NULL) {
		child = gtk_flow_box_get_child_at_index(GTK_FLOW_BOX(inner_box), 0);
	}
	gboolean is_visible = gtk_widget_get_visible(GTK_WIDGET(child));' \
          --replace-fail 'static void move_forward(void) {
	user_moved = true;' \
'static void move_forward(void) {
	user_moved = true;
	if(columns == 1 && outer_orientation == GTK_ORIENTATION_VERTICAL) {
		move_selection(1, TRUE);
		return;
	}' \
          --replace-fail 'static void move_backward(void) {
	user_moved = true;' \
'static void move_backward(void) {
	user_moved = true;
	if(columns == 1 && outer_orientation == GTK_ORIENTATION_VERTICAL) {
		move_selection(-1, TRUE);
		return;
	}' \
          --replace-fail '	gtk_entry_set_placeholder_text(GTK_ENTRY(entry), prompt);
	gtk_container_add(GTK_CONTAINER(outer_box), entry);' \
'	GtkWidget* entry_overlay = gtk_overlay_new();
	gtk_container_add(GTK_CONTAINER(entry_overlay), entry);
	placeholder_label = gtk_label_new(prompt);
	gtk_widget_set_name(placeholder_label, "placeholder");
	gtk_widget_set_halign(placeholder_label, GTK_ALIGN_START);
	gtk_widget_set_valign(placeholder_label, GTK_ALIGN_CENTER);
	gtk_widget_set_no_show_all(placeholder_label, TRUE);
	gtk_overlay_add_overlay(GTK_OVERLAY(entry_overlay), placeholder_label);
	gtk_overlay_set_overlay_pass_through(GTK_OVERLAY(entry_overlay), placeholder_label, TRUE);
	gtk_container_add(GTK_CONTAINER(outer_box), entry_overlay);
	g_signal_connect(entry, "changed", G_CALLBACK(entry_text_changed), NULL);
	g_signal_connect(entry, "preedit-changed", G_CALLBACK(entry_preedit_changed), NULL);
	update_placeholder();' \
          --replace-fail 'static gboolean do_search(gpointer data) {' \
'#define WOFI_MATCH_R 0xcbcb
#define WOFI_MATCH_G 0x4b4b
#define WOFI_MATCH_B 0x1616

static gboolean wofi_chr_eq(gunichar a, gunichar b) {
	if(insensitive) {
		return g_unichar_tolower(a) == g_unichar_tolower(b);
	}
	return a == b;
}

/* text 안에서 needle(길이 nl)이 처음 연속으로 나타나는 위치. 없으면 -1 */
static glong wofi_find_substr(const gunichar* t, glong tl, const gunichar* n, glong nl) {
	if(nl <= 0) {
		return -1;
	}
	for(glong i = 0; i + nl <= tl; ++i) {
		glong j = 0;
		while(j < nl && wofi_chr_eq(t[i + j], n[j])) {
			++j;
		}
		if(j == nl) {
			return i;
		}
	}
	return -1;
}

/* needle 의 글자가 순서대로(떨어져도 됨) 모두 나타나면 위치를 hit 에 표시하고 TRUE */
static gboolean wofi_mark_subseq(const gunichar* t, glong tl, const gunichar* n, glong nl, gboolean* hit) {
	glong ti = 0;
	glong marked[nl > 0 ? nl : 1];
	for(glong ni = 0; ni < nl; ++ni) {
		while(ti < tl && !wofi_chr_eq(t[ti], n[ni])) {
			++ti;
		}
		if(ti >= tl) {
			return FALSE;
		}
		marked[ni] = ti++;
	}
	for(glong ni = 0; ni < nl; ++ni) {
		hit[marked[ni]] = TRUE;
	}
	return TRUE;
}

static void wofi_mark_range(gboolean* hit, glong from, glong len) {
	for(glong i = 0; i < len; ++i) {
		hit[from + i] = TRUE;
	}
}

static void highlight_label_text(GtkWidget* label, const gchar* needle) {
	const gchar* text = gtk_label_get_text(GTK_LABEL(label));
	if(needle == NULL || needle[0] == 0 || text == NULL || text[0] == 0) {
		gtk_label_set_attributes(GTK_LABEL(label), NULL);
		return;
	}
	glong tl = g_utf8_strlen(text, -1);
	gunichar* t = g_utf8_to_ucs4_fast(text, -1, NULL);
	gboolean* hit = g_new0(gboolean, tl);
	gboolean any = FALSE;

	if(matching == MATCHING_MODE_MULTI_CONTAINS) {
		gchar** tokens = g_strsplit(needle, " ", -1);
		for(gchar** tok = tokens; *tok != NULL; ++tok) {
			if((*tok)[0] == 0) {
				continue;
			}
			glong nl = g_utf8_strlen(*tok, -1);
			gunichar* n = g_utf8_to_ucs4_fast(*tok, -1, NULL);
			glong pos = wofi_find_substr(t, tl, n, nl);
			if(pos >= 0) {
				wofi_mark_range(hit, pos, nl);
				any = TRUE;
			}
			g_free(n);
		}
		g_strfreev(tokens);
	} else {
		glong nl = g_utf8_strlen(needle, -1);
		gunichar* n = g_utf8_to_ucs4_fast(needle, -1, NULL);
		glong pos = wofi_find_substr(t, tl, n, nl);
		if(pos >= 0) {
			wofi_mark_range(hit, pos, nl);
			any = TRUE;
		} else if(matching == MATCHING_MODE_FUZZY) {
			any = wofi_mark_subseq(t, tl, n, nl, hit);
		}
		g_free(n);
	}

	if(!any) {
		gtk_label_set_attributes(GTK_LABEL(label), NULL);
	} else {
		PangoAttrList* list = pango_attr_list_new();
		glong i = 0;
		while(i < tl) {
			if(!hit[i]) {
				++i;
				continue;
			}
			glong start = i;
			while(i < tl && hit[i]) {
				++i;
			}
			guint start_byte = g_utf8_offset_to_pointer(text, start) - text;
			guint end_byte = g_utf8_offset_to_pointer(text, i) - text;
			PangoAttribute* color = pango_attr_foreground_new(WOFI_MATCH_R, WOFI_MATCH_G, WOFI_MATCH_B);
			color->start_index = start_byte;
			color->end_index = end_byte;
			pango_attr_list_insert(list, color);
			PangoAttribute* bold = pango_attr_weight_new(PANGO_WEIGHT_BOLD);
			bold->start_index = start_byte;
			bold->end_index = end_byte;
			pango_attr_list_insert(list, bold);
		}
		gtk_label_set_attributes(GTK_LABEL(label), list);
		pango_attr_list_unref(list);
	}
	g_free(hit);
	g_free(t);
}

static void highlight_child(GtkWidget* child, gpointer data) {
	(void) data;
	GtkWidget* box = gtk_bin_get_child(GTK_BIN(child));
	if(box == NULL) {
		return;
	}
	if(GTK_IS_EXPANDER(box)) {
		box = gtk_expander_get_label_widget(GTK_EXPANDER(box));
	}
	if(box == NULL || !GTK_IS_CONTAINER(box)) {
		return;
	}
	GList* kids = gtk_container_get_children(GTK_CONTAINER(box));
	for(GList* it = kids; it != NULL; it = it->next) {
		if(GTK_IS_LABEL(it->data) && g_strcmp0(gtk_widget_get_name(GTK_WIDGET(it->data)), "text") == 0) {
			highlight_label_text(GTK_WIDGET(it->data), filter);
		}
	}
	g_list_free(kids);
}

static gboolean do_search(gpointer data) {' \
          --replace-fail '		if(child != NULL) {
			gtk_flow_box_select_child(GTK_FLOW_BOX(inner_box), child);
		}
	}
	return G_SOURCE_CONTINUE;' \
'		if(child != NULL) {
			gtk_flow_box_select_child(GTK_FLOW_BOX(inner_box), child);
		}
		gtk_container_foreach(GTK_CONTAINER(inner_box), highlight_child, NULL);
	}
	return G_SOURCE_CONTINUE;' \
          --replace-fail 'static gboolean _insert_widget(gpointer data) {' \
'static GtkWidget* placeholder_label = NULL;
static gboolean entry_preedit_active = FALSE;

static void update_placeholder(void) {
	if(placeholder_label == NULL) {
		return;
	}
	const gchar* text = gtk_entry_get_text(GTK_ENTRY(entry));
	gtk_widget_set_visible(placeholder_label, (text == NULL || text[0] == 0) && !entry_preedit_active && !hide_search);
}

static void entry_text_changed(GtkEditable* editable, gpointer data) {
	(void) editable;
	(void) data;
	update_placeholder();
}

static void entry_preedit_changed(GtkEntry* editable, gchar* preedit, gpointer data) {
	(void) editable;
	(void) data;
	entry_preedit_active = preedit != NULL && preedit[0] != 0;
	update_placeholder();
}

static gboolean hover_select(GtkWidget* widget, GdkEventMotion* event, gpointer data) {
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
