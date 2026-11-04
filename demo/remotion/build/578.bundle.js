"use strict";
(self["webpackChunktraceloop_hackathon_film"] = self["webpackChunktraceloop_hackathon_film"] || []).push([[578],{

/***/ 8578
(__unused_webpack___webpack_module__, __webpack_exports__, __webpack_require__) {

/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   VideoMattingModal: () => (/* binding */ VideoMattingModal)
/* harmony export */ });
/* harmony import */ var _index_ts7drhwc_mjs__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(3656);
/* harmony import */ var _index_kwxewaaz_mjs__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(1528);
/* harmony import */ var _index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(6659);
/* harmony import */ var _index_gjr0ae8m_mjs__WEBPACK_IMPORTED_MODULE_3__ = __webpack_require__(8304);
/* harmony import */ var _index_zpf6xem0_mjs__WEBPACK_IMPORTED_MODULE_4__ = __webpack_require__(1666);
/* harmony import */ var _index_dapnr3e1_mjs__WEBPACK_IMPORTED_MODULE_5__ = __webpack_require__(8986);
/* harmony import */ var _index_fhmraatf_mjs__WEBPACK_IMPORTED_MODULE_6__ = __webpack_require__(1233);
/* harmony import */ var _remotion_studio_shared__WEBPACK_IMPORTED_MODULE_7__ = __webpack_require__(8397);
Object(function webpackMissingModule() { var e = new Error("Cannot find module '@remotion/video-matting'"); e.code = 'MODULE_NOT_FOUND'; throw e; }());
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_9__ = __webpack_require__(3025);
/* harmony import */ var react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__ = __webpack_require__(8917);








// src/components/VideoMatting/VideoMattingModal.tsx




var MODELS = Object(function webpackMissingModule() { var e = new Error("Cannot find module '@remotion/video-matting'"); e.code = 'MODULE_NOT_FOUND'; throw e; }())();
var controlStyle = { width: 330, maxWidth: "100%" };
var panelStyle = {
  ..._index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .optionsPanel */ .Z6,
  flexDirection: "column",
  paddingTop: 16
};
var modalStyle = {
  ..._index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .outerModalStyle */ .uT,
  height: "auto",
  maxHeight: "calc(100vh - 40px)",
  minHeight: _index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .outerModalStyle */ .uT.height,
  outline: "none"
};
var modalLayout = {
  ..._index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .horizontalLayout */ .D6,
  flex: "1 1 auto"
};
var hiddenPanel = { display: "none" };
var validationStyle = { padding: "0 16px 8px" };
var makeOptions = ({
  items,
  selected,
  setSelected
}) => items.map(({ id, label: optionLabel }) => ({
  type: "item",
  id,
  value: id,
  label: optionLabel,
  leftItem: id === selected ? /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsx)(_index_kwxewaaz_mjs__WEBPACK_IMPORTED_MODULE_1__/* .Checkmark */ .MG, {}) : null,
  keyHint: null,
  quickSwitcherLabel: null,
  subMenu: null,
  disabled: false,
  onClick: () => setSelected(id)
}));
var VideoMattingModal = ({
  displayName,
  src,
  target
}) => {
  const [tab, setTab] = (0,react__WEBPACK_IMPORTED_MODULE_9__.useState)("remove");
  const isModelCached = (0,react__WEBPACK_IMPORTED_MODULE_9__.useCallback)((selectedModel) => Object(function webpackMissingModule() { var e = new Error("Cannot find module '@remotion/video-matting'"); e.code = 'MODULE_NOT_FOUND'; throw e; }())({ model: selectedModel }), []);
  const cachedModels = (0,_index_zpf6xem0_mjs__WEBPACK_IMPORTED_MODULE_4__/* .useModelCacheStatus */ .X)({
    isModelCached,
    models: MODELS,
    refreshKey: tab
  });
  const baseName = (0,react__WEBPACK_IMPORTED_MODULE_9__.useMemo)(() => (0,_index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .getDefaultOutputBaseName */ .Jj)(src, displayName, "video"), [displayName, src]);
  const [outName, setOutName] = (0,react__WEBPACK_IMPORTED_MODULE_9__.useState)(`${baseName}-no-background.webm`);
  const [model, setModel] = (0,react__WEBPACK_IMPORTED_MODULE_9__.useState)("modnet");
  const [audio, setAudio] = (0,react__WEBPACK_IMPORTED_MODULE_9__.useState)("keep");
  const [videoBitrate, setVideoBitrate] = (0,react__WEBPACK_IMPORTED_MODULE_9__.useState)("very-high");
  const [support, setSupport] = (0,react__WEBPACK_IMPORTED_MODULE_9__.useState)({ type: "checking" });
  const staticFiles = (0,_index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .useStaticFiles */ .JM)();
  const { addVideoMattingJob, videoMattingJobs } = (0,react__WEBPACK_IMPORTED_MODULE_9__.useContext)(_index_kwxewaaz_mjs__WEBPACK_IMPORTED_MODULE_1__/* .RenderQueueContext */ .x7);
  const { setSelectedModal } = (0,react__WEBPACK_IMPORTED_MODULE_9__.useContext)(_index_kwxewaaz_mjs__WEBPACK_IMPORTED_MODULE_1__/* .SetSelectedModalContext */ .Mq);
  const { setSidebarCollapsedState } = (0,react__WEBPACK_IMPORTED_MODULE_9__.useContext)(_index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .SidebarContext */ .I0);
  (0,react__WEBPACK_IMPORTED_MODULE_9__.useEffect)(() => {
    let cancelled = false;
    setSupport({ type: "checking" });
    Object(function webpackMissingModule() { var e = new Error("Cannot find module '@remotion/video-matting'"); e.code = 'MODULE_NOT_FOUND'; throw e; }())({ model }).then((result) => {
      if (!cancelled) {
        setSupport(result.supported ? { type: "supported" } : { type: "unsupported", message: result.detailedReason });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [model]);
  const normalizedOutput = outName.normalize("NFC").toLowerCase();
  const queuedOutputs = new Set(videoMattingJobs.filter((job) => job.status === "idle" || job.status === "running" || job.status === "saving").map((job) => job.outName).map((name) => name.normalize("NFC").toLowerCase()));
  const outputError = (0,_index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .validatePublicOutputName */ .MD)({ extension: ".webm", outName }) ?? (queuedOutputs.has(normalizedOutput) ? "Another background removal job is using this output file" : null);
  const outputExists = staticFiles.some((file) => file.name.normalize("NFC").toLowerCase() === normalizedOutput);
  const canSubmit = support.type === "supported" && outputError === null;
  const modelOptions = (0,react__WEBPACK_IMPORTED_MODULE_9__.useMemo)(() => makeOptions({
    items: MODELS.map((item) => ({
      id: item.name,
      label: `${item.name} · ${(0,_remotion_studio_shared__WEBPACK_IMPORTED_MODULE_7__/* .formatBytes */ .z3)(item.webGpuDownloadSize)}${cachedModels.has(item.name) ? " · Downloaded" : ""}`
    })),
    selected: model,
    setSelected: setModel
  }), [cachedModels, model]);
  const audioOptions = (0,react__WEBPACK_IMPORTED_MODULE_9__.useMemo)(() => makeOptions({
    items: [
      { id: "keep", label: "Keep original audio" },
      { id: "none", label: "No audio" }
    ],
    selected: audio,
    setSelected: setAudio
  }), [audio]);
  const qualityOptions = (0,react__WEBPACK_IMPORTED_MODULE_9__.useMemo)(() => makeOptions({
    items: ["very-low", "low", "medium", "high", "very-high"].map((id) => ({
      id,
      label: id.split("-").map((part) => part[0].toUpperCase() + part.slice(1)).join(" ")
    })),
    selected: videoBitrate,
    setSelected: setVideoBitrate
  }), [videoBitrate]);
  const submit = (0,react__WEBPACK_IMPORTED_MODULE_9__.useCallback)(() => {
    if (!canSubmit)
      return;
    addVideoMattingJob({
      src,
      displayName,
      outName,
      model,
      audio,
      videoBitrate,
      target
    });
    setSidebarCollapsedState({ left: null, right: "expanded" });
    (0,_index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .persistSelectedOptionsSidebarPanel */ .Gd)("renders");
    _index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .optionsSidebarTabs */ .nm.current?.selectRendersPanel();
    setSelectedModal(null);
  }, [
    addVideoMattingJob,
    audio,
    canSubmit,
    displayName,
    outName,
    model,
    setSelectedModal,
    setSidebarCollapsedState,
    src,
    target,
    videoBitrate
  ]);
  const title = `Remove background from ${displayName}`;
  return /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsx)(_index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .DismissableModal */ .sb, {
    ariaLabel: title,
    children: /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsxs)("div", {
      style: modalStyle,
      children: [
        /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsx)(_index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .ModalHeader */ .rQ, {
          title
        }),
        /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsxs)("div", {
          style: _index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .container */ .kL,
          children: [
            /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsx)("div", {
              style: _index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .flexer */ .lw
            }),
            /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsx)(_index_kwxewaaz_mjs__WEBPACK_IMPORTED_MODULE_1__/* .Button */ .$n, {
              disabled: !canSubmit,
              onClick: submit,
              "aria-label": support.type === "unsupported" ? support.message : undefined,
              style: {
                ..._index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .buttonStyle */ .i9,
                backgroundColor: canSubmit ? _index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .buttonStyle */ .i9.backgroundColor : _index_ts7drhwc_mjs__WEBPACK_IMPORTED_MODULE_0__/* .BLUE_DISABLED */ .er
              },
              children: "Remove background"
            })
          ]
        }),
        /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsxs)("div", {
          style: modalLayout,
          children: [
            /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsxs)("div", {
              style: _index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .leftSidebar */ .K8,
              children: [
                /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsx)(_index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .VerticalTab */ .sM, {
                  autoFocus: true,
                  onClick: () => setTab("remove"),
                  renderIcon: (color) => /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsx)("div", {
                    style: _index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .iconContainer */ .zc,
                    children: /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsx)(_index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .GearIcon */ .L6, {
                      color,
                      style: _index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .icon */ .Kk
                    })
                  }),
                  selected: tab === "remove",
                  style: _index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .horizontalTab */ .So,
                  children: "General"
                }),
                /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsx)(_index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .VerticalTab */ .sM, {
                  onClick: () => setTab("models"),
                  renderIcon: (color) => /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsx)("div", {
                    style: _index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .iconContainer */ .zc,
                    children: /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsx)(_index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .ModelsIcon */ .oi, {
                      color,
                      style: _index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .icon */ .Kk
                    })
                  }),
                  selected: tab === "models",
                  style: _index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .horizontalTab */ .So,
                  children: "Models"
                })
              ]
            }),
            /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsxs)("div", {
              style: tab === "remove" ? panelStyle : hiddenPanel,
              className: _index_kwxewaaz_mjs__WEBPACK_IMPORTED_MODULE_1__/* .VERTICAL_SCROLLBAR_CLASSNAME */ .uV,
              children: [
                /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsx)(_index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .RenderModalOutputName */ .Os, {
                  ariaLabel: "Video output file",
                  existingOutputPath: window.remotion_publicFolderExists ? `${window.remotion_publicFolderExists}/${outName}` : null,
                  existence: outputExists,
                  inputStyle: _index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .input */ .hF,
                  label: "Output in public/",
                  onValueChange: (event) => setOutName(event.target.value),
                  outName,
                  validationMessage: outputError
                }),
                /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsx)(_index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .RenderModalHr */ .Yb, {}),
                /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsxs)("div", {
                  style: _index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .optionRow */ .wV,
                  children: [
                    /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsx)("div", {
                      style: _index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .label */ .Pf,
                      children: "Model"
                    }),
                    /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsx)("div", {
                      style: _index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .rightRow */ .jm,
                      children: /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsx)(_index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .Combobox */ .G3, {
                        values: modelOptions,
                        selectedId: model,
                        "aria-label": "Model",
                        style: controlStyle
                      })
                    })
                  ]
                }),
                support.type === "unsupported" ? /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsx)("div", {
                  style: validationStyle,
                  children: /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsx)(_index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .ValidationMessage */ .Xl, {
                    align: "flex-end",
                    message: support.message,
                    type: "error"
                  })
                }) : null,
                /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsxs)("div", {
                  style: _index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .optionRow */ .wV,
                  children: [
                    /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsx)("div", {
                      style: _index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .label */ .Pf,
                      children: "Audio"
                    }),
                    /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsx)("div", {
                      style: _index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .rightRow */ .jm,
                      children: /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsx)(_index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .Combobox */ .G3, {
                        values: audioOptions,
                        selectedId: audio,
                        "aria-label": "Audio",
                        style: controlStyle
                      })
                    })
                  ]
                }),
                /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsxs)("div", {
                  style: _index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .optionRow */ .wV,
                  children: [
                    /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsx)("div", {
                      style: _index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .label */ .Pf,
                      children: "Video quality"
                    }),
                    /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsx)("div", {
                      style: _index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .rightRow */ .jm,
                      children: /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsx)(_index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_2__/* .Combobox */ .G3, {
                        values: qualityOptions,
                        selectedId: String(videoBitrate),
                        "aria-label": "Video quality",
                        style: controlStyle
                      })
                    })
                  ]
                })
              ]
            }),
            /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_10__.jsx)(_index_fhmraatf_mjs__WEBPACK_IMPORTED_MODULE_6__/* .Models2 */ .N, {
              description: `Models are downloaded automatically when needed.
You can also manage the browser cache here.`,
              indent: true,
              visible: tab === "models"
            })
          ]
        })
      ]
    })
  });
};



/***/ },

/***/ 8986
(__unused_webpack___webpack_module__, __webpack_exports__, __webpack_require__) {

/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   P: () => (/* binding */ ModelManager)
/* harmony export */ });
/* harmony import */ var _index_ts7drhwc_mjs__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(3656);
/* harmony import */ var _index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(6659);
/* harmony import */ var _index_kwxewaaz_mjs__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(1528);
/* harmony import */ var _remotion_studio_shared__WEBPACK_IMPORTED_MODULE_3__ = __webpack_require__(8397);
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_4__ = __webpack_require__(3025);
/* harmony import */ var react_jsx_runtime__WEBPACK_IMPORTED_MODULE_5__ = __webpack_require__(8917);




// src/components/ModelManager.tsx



var modelPanel = {
  ..._index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_1__/* .optionsPanel */ .Z6,
  flexDirection: "column"
};
var hiddenPanel = { display: "none" };
var container = {
  boxSizing: "border-box",
  flex: 1,
  fontFamily: "sans-serif",
  minWidth: 0,
  padding: "16px 16px 0",
  width: "100%"
};
var flushContainer = {
  ...container,
  padding: "16px 0 0"
};
var descriptionStyle = {
  color: _index_ts7drhwc_mjs__WEBPACK_IMPORTED_MODULE_0__/* .LIGHT_TEXT */ .hf,
  fontSize: 13,
  lineHeight: 1.5,
  margin: 0,
  whiteSpace: "pre-line"
};
var list = { marginTop: 14 };
var modelRow = {
  alignItems: "center",
  display: "flex",
  gap: 10,
  minHeight: 38
};
var modelIcon = {
  flexShrink: 0,
  height: 16,
  width: 16
};
var statusIcon = {
  flexShrink: 0,
  height: 14,
  width: 14
};
var modelName = {
  color: _index_ts7drhwc_mjs__WEBPACK_IMPORTED_MODULE_0__/* .LIGHT_TEXT */ .hf,
  flex: 1,
  fontFamily: "monospace",
  fontSize: 13,
  lineHeight: 1.4,
  minWidth: 0,
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap"
};
var status = {
  color: _index_ts7drhwc_mjs__WEBPACK_IMPORTED_MODULE_0__/* .LIGHT_TEXT */ .hf,
  fontSize: 12,
  fontVariantNumeric: "tabular-nums",
  lineHeight: 1.4,
  whiteSpace: "nowrap"
};
var actionIcon = { height: 14, width: 14 };
var actionSlot = {
  alignItems: "center",
  display: "inline-flex",
  flexShrink: 0,
  height: 24,
  justifyContent: "center",
  width: 24
};
var ModelManager = ({
  ariaLabel,
  availableModels,
  description,
  indent,
  isModelCached,
  loadModel,
  prepare,
  removeModel,
  visible
}) => {
  const mounted = (0,react__WEBPACK_IMPORTED_MODULE_4__.useRef)(true);
  const initialized = (0,react__WEBPACK_IMPORTED_MODULE_4__.useRef)(false);
  const [cachedModels, setCachedModels] = (0,react__WEBPACK_IMPORTED_MODULE_4__.useState)(null);
  const [actionState, setActionState] = (0,react__WEBPACK_IMPORTED_MODULE_4__.useState)({
    type: "idle"
  });
  const [cacheCheckError, setCacheCheckError] = (0,react__WEBPACK_IMPORTED_MODULE_4__.useState)(null);
  (0,react__WEBPACK_IMPORTED_MODULE_4__.useEffect)(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  (0,react__WEBPACK_IMPORTED_MODULE_4__.useEffect)(() => {
    if (!visible || initialized.current) {
      return;
    }
    initialized.current = true;
    Promise.resolve().then(() => prepare?.()).then(() => Promise.all(availableModels.map(async ({ name }) => await isModelCached(name) ? name : null))).then((models) => {
      if (mounted.current) {
        const cached = new Set;
        for (const model of models) {
          if (model !== null) {
            cached.add(model);
          }
        }
        setCachedModels(cached);
      }
    }).catch((error) => {
      if (mounted.current) {
        setCachedModels(new Set);
        setCacheCheckError(error instanceof Error ? error.message : String(error));
      }
    });
  }, [availableModels, isModelCached, prepare, visible]);
  const downloadModel = (0,react__WEBPACK_IMPORTED_MODULE_4__.useCallback)((model) => {
    setActionState({ type: "downloading", model, progress: 0 });
    loadModel(model, (progress) => {
      if (mounted.current) {
        setActionState({ type: "downloading", model, progress });
      }
    }).then(() => {
      if (mounted.current) {
        setCachedModels((current) => new Set([...current ?? [], model]));
        setActionState({ type: "idle" });
      }
    }).catch((error) => {
      if (mounted.current) {
        setActionState({
          type: "error",
          model,
          message: error instanceof Error ? error.message : String(error)
        });
      }
    });
  }, [loadModel]);
  const remove = (0,react__WEBPACK_IMPORTED_MODULE_4__.useCallback)((model) => {
    setActionState({ type: "removing", model });
    removeModel(model).then(() => {
      if (mounted.current) {
        setCachedModels((current) => {
          const next = new Set(current ?? []);
          next.delete(model);
          return next;
        });
        setActionState({ type: "idle" });
      }
    }).catch((error) => {
      if (mounted.current) {
        setActionState({
          type: "error",
          model,
          message: error instanceof Error ? error.message : String(error)
        });
      }
    });
  }, [removeModel]);
  const renderDownloadIcon = (0,react__WEBPACK_IMPORTED_MODULE_4__.useCallback)((color) => {
    return /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_5__.jsx)(_index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_1__/* .CloudDownloadIcon */ .$w, {
      color,
      style: actionIcon
    });
  }, []);
  const renderRemoveIcon = (0,react__WEBPACK_IMPORTED_MODULE_4__.useCallback)((color) => {
    return /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_5__.jsx)(_index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_1__/* .TrashIcon */ .uc, {
      color,
      style: actionIcon
    });
  }, []);
  const actionInProgress = actionState.type === "downloading" || actionState.type === "removing";
  return /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_5__.jsx)("div", {
    style: visible ? modelPanel : hiddenPanel,
    className: _index_kwxewaaz_mjs__WEBPACK_IMPORTED_MODULE_2__/* .VERTICAL_SCROLLBAR_CLASSNAME */ .uV,
    children: /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_5__.jsxs)("div", {
      style: indent ? container : flushContainer,
      children: [
        description === null ? null : /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_5__.jsx)("p", {
          style: descriptionStyle,
          children: description
        }),
        cacheCheckError ? /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_5__.jsx)(_index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_1__/* .ValidationMessage */ .Xl, {
          align: "flex-start",
          message: cacheCheckError,
          type: "error"
        }) : null,
        /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_5__.jsx)("div", {
          style: description === null ? undefined : list,
          role: "list",
          "aria-label": ariaLabel,
          children: availableModels.map((model) => {
            const cached = cachedModels?.has(model.name) ?? false;
            const processingThisModel = actionState.type !== "idle" && actionState.type !== "error" && actionState.model === model.name;
            const progress = actionState.type === "downloading" && actionState.model === model.name ? actionState.progress : null;
            const modelStatus = processingThisModel ? actionState.type === "removing" ? "Removing…" : `Downloading${progress === null ? "…" : ` ${Math.round(progress * 100)}%`}` : actionState.type === "error" && actionState.model === model.name ? actionState.message : (0,_remotion_studio_shared__WEBPACK_IMPORTED_MODULE_3__/* .formatBytes */ .z3)(model.webGpuDownloadSize);
            return /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_5__.jsxs)("div", {
              role: "listitem",
              style: modelRow,
              children: [
                /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_5__.jsx)(_index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_1__/* .ModelsIcon */ .oi, {
                  "aria-hidden": true,
                  color: _index_ts7drhwc_mjs__WEBPACK_IMPORTED_MODULE_0__/* .LIGHT_TEXT */ .hf,
                  style: modelIcon
                }),
                /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_5__.jsx)("span", {
                  style: modelName,
                  children: model.name
                }),
                /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_5__.jsx)("span", {
                  role: "group",
                  style: status,
                  "aria-label": modelStatus,
                  children: modelStatus
                }),
                cached ? /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_5__.jsx)(_index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_1__/* .CheckCircleFilled */ .Pk, {
                  "aria-hidden": true,
                  style: { ...statusIcon, fill: _index_ts7drhwc_mjs__WEBPACK_IMPORTED_MODULE_0__/* .BLUE */ .ft }
                }) : null,
                processingThisModel ? /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_5__.jsx)("span", {
                  style: actionSlot,
                  children: /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_5__.jsx)(_index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_1__/* .Spinner */ .y$, {
                    duration: 0.5,
                    size: 14
                  })
                }) : cached ? /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_5__.jsx)(_index_kwxewaaz_mjs__WEBPACK_IMPORTED_MODULE_2__/* .ActionTooltip */ .mT, {
                  label: "Uninstall",
                  shortcut: null,
                  delay: 800,
                  dismissOnClick: true,
                  children: /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_5__.jsx)(_index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_1__/* .InlineAction */ .gs, {
                    "aria-label": `Remove ${model.name}`,
                    disabled: actionInProgress,
                    onClick: () => remove(model.name),
                    renderAction: renderRemoveIcon,
                    variant: null
                  })
                }) : /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_5__.jsx)(_index_kwxewaaz_mjs__WEBPACK_IMPORTED_MODULE_2__/* .ActionTooltip */ .mT, {
                  label: "Install",
                  shortcut: null,
                  delay: 800,
                  dismissOnClick: true,
                  children: /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_5__.jsx)(_index_kewagct1_mjs__WEBPACK_IMPORTED_MODULE_1__/* .InlineAction */ .gs, {
                    "aria-label": `Download ${model.name}`,
                    disabled: cachedModels === null || actionInProgress,
                    onClick: () => downloadModel(model.name),
                    renderAction: renderDownloadIcon,
                    variant: null
                  })
                })
              ]
            }, model.name);
          })
        })
      ]
    })
  });
};




/***/ },

/***/ 1233
(__unused_webpack___webpack_module__, __webpack_exports__, __webpack_require__) {

/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   N: () => (/* binding */ Models2)
/* harmony export */ });
/* harmony import */ var _index_dapnr3e1_mjs__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(8986);
Object(function webpackMissingModule() { var e = new Error("Cannot find module '@remotion/video-matting'"); e.code = 'MODULE_NOT_FOUND'; throw e; }());
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(3025);
/* harmony import */ var react_jsx_runtime__WEBPACK_IMPORTED_MODULE_3__ = __webpack_require__(8917);


// src/components/VideoMatting/Models.tsx



var AVAILABLE_MODELS = Object(function webpackMissingModule() { var e = new Error("Cannot find module '@remotion/video-matting'"); e.code = 'MODULE_NOT_FOUND'; throw e; }())();
var Models2 = ({ description, indent, visible }) => {
  const isModelCached = (0,react__WEBPACK_IMPORTED_MODULE_2__.useCallback)((model) => Object(function webpackMissingModule() { var e = new Error("Cannot find module '@remotion/video-matting'"); e.code = 'MODULE_NOT_FOUND'; throw e; }())({ model }), []);
  const loadModel = (0,react__WEBPACK_IMPORTED_MODULE_2__.useCallback)((model, onProgress) => Object(function webpackMissingModule() { var e = new Error("Cannot find module '@remotion/video-matting'"); e.code = 'MODULE_NOT_FOUND'; throw e; }())({
    model,
    onProgress: (progress) => onProgress(progress.progress)
  }), []);
  const removeModel = (0,react__WEBPACK_IMPORTED_MODULE_2__.useCallback)((model) => Object(function webpackMissingModule() { var e = new Error("Cannot find module '@remotion/video-matting'"); e.code = 'MODULE_NOT_FOUND'; throw e; }())({ model }), []);
  return /* @__PURE__ */ (0,react_jsx_runtime__WEBPACK_IMPORTED_MODULE_3__.jsx)(_index_dapnr3e1_mjs__WEBPACK_IMPORTED_MODULE_0__/* .ModelManager */ .P, {
    ariaLabel: "Video matting models",
    availableModels: AVAILABLE_MODELS,
    description,
    indent,
    isModelCached,
    loadModel,
    prepare: null,
    removeModel,
    visible
  });
};




/***/ },

/***/ 1666
(__unused_webpack___webpack_module__, __webpack_exports__, __webpack_require__) {

/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   X: () => (/* binding */ useModelCacheStatus)
/* harmony export */ });
/* harmony import */ var react__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(3025);
// src/components/use-model-cache-status.ts

var useModelCacheStatus = ({
  isModelCached,
  models,
  refreshKey
}) => {
  const [cachedModels, setCachedModels] = (0,react__WEBPACK_IMPORTED_MODULE_0__.useState)(new Set);
  (0,react__WEBPACK_IMPORTED_MODULE_0__.useEffect)(() => {
    let cancelled = false;
    Promise.all(models.map(async ({ name }) => ({
      cached: await isModelCached(name),
      name
    }))).then((results) => {
      if (!cancelled) {
        const nextCachedModels = new Set;
        for (const result of results) {
          if (result.cached) {
            nextCachedModels.add(result.name);
          }
        }
        setCachedModels(nextCachedModels);
      }
    }).catch(() => {
      if (!cancelled) {
        setCachedModels(new Set);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [isModelCached, models, refreshKey]);
  return cachedModels;
};




/***/ }

}]);
//# sourceMappingURL=578.bundle.js.map