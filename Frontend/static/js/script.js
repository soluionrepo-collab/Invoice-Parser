// /static/js/script.js

const $  = (s, r=document) => r.querySelector(s);
const $$ = (s, r=document) => Array.from(r.querySelectorAll(s));
const API_BASE_URL = "http://127.0.0.1:8000";

/* ---------- Toasts ---------- */
const successToast = $("#successToast");
const errorToast   = $("#errorToast");
const errorMsgEl   = $("#errorMessage");

function showToast(element, msg) {
    if (!element) return;
    element.querySelector("span").textContent = msg;
    element.classList.add("show");
    setTimeout(() => element.classList.remove("show"), 3000);
}
const showSuccess = (msg = "Success") => showToast(successToast, msg);
const showError = (msg = "Error") => showToast(errorToast, msg);

/* ---------- Auth ---------- */
function getToken() { return sessionStorage.getItem("authToken"); }
function getUser() { try { return JSON.parse(sessionStorage.getItem("user")); } catch { return { name: "User" }; } }
function requireAuth() {
    if (!getToken()) {
        window.location.replace("login.html");
        return false;
    }
    return true;
}
async function logout() {
    sessionStorage.removeItem("user");
    sessionStorage.removeItem("authToken");
    window.location.replace("login.html");
}

/* ---------- App State Management ---------- */
function showState(state) {
    $$('.page-section').forEach(el => el.style.display = 'none');
    const section = $(`#${state}Section`);
    if (section) {
        section.style.display = 'block';
    }
}

/* ---------- Polygon Processing Functions ---------- */
function normalizePolygon(polygon, imageWidth, imageHeight) {
    if (!polygon || !Array.isArray(polygon)) return [];
    
    // Handle different polygon formats
    let points = [];
    
    if (polygon.length === 0) return [];
    
    // Check if it's array of [x, y] pairs
    if (Array.isArray(polygon[0]) && polygon[0].length === 2) {
        points = polygon;
    }
    // Check if it's flat array [x1, y1, x2, y2, ...]
    else if (typeof polygon[0] === 'number' && polygon.length % 2 === 0) {
        for (let i = 0; i < polygon.length; i += 2) {
            points.push([polygon[i], polygon[i + 1]]);
        }
    }
    // Check if it's array of objects with x, y properties
    else if (typeof polygon[0] === 'object' && polygon[0].x !== undefined) {
        points = polygon.map(p => [p.x, p.y]);
    }
    // Check if it's tuple format
    else if (Array.isArray(polygon[0]) && polygon[0].length === 2) {
        points = polygon;
    }
    
    // Validate and clean points
    let processedPoints = points.filter(p => Array.isArray(p) && p.length >= 2 && 
                                  typeof p[0] === 'number' && typeof p[1] === 'number')
                                .map(p => [Number(p[0]), Number(p[1])]);
    
    if (processedPoints.length < 3) return []; // Need at least 3 points for a polygon
    
    // *** CRITICAL FIX: Scale from inches to points (multiply by 72) ***
    // This matches your Python function logic: points = [fitz.Point(x * 72, y * 72) for x, y in poly]
    return processedPoints.map(([x, y]) => [x * 72, y * 72]);
}

function coerceSignatureVerdict(sig){
    if("boolean"==typeof sig)return sig;
    if(!sig||"object"!=typeof sig)return null;
    if("boolean"==typeof sig.signature)return sig.signature;
    if("boolean"==typeof sig.is_signed)return sig.is_signed;
    if("boolean"==typeof sig.signed)return sig.signed;
    const s=(sig.status||sig.verdict||"").toString().toLowerCase();
    return["valid","verified","signed","present"].includes(s)?!0:["invalid","unverified","not-signed","absent"].includes(s)?!1:null;
}

class App {
    constructor() {
        if (!requireAuth()) return;
        this.initDomElements();
        this.initState();
        this.bindEvents();
        this.initHeader();
        showState('upload');
    }

    initDomElements() {
        this.uploadArea = $("#uploadArea");
        this.fileInput = $("#fileInput");
        this.preSubmitPreview = $("#preSubmitPreview");
        this.previewCard = $("#previewCard");
        this.submitBtn = $("#submitBtn");
        this.cancelBtn = $("#cancelBtn");
        this.proc = $("#processingSection");
        this.stepBar = $("#stepBar");
        this.steps = { upload: $("#stepUpload"), extract: $("#stepExtract"), map: $("#stepMap") };
        this.zipSection = $("#zipContentsSection");
        this.zipBody = $("#zipTableBody");
        this.zipCount = $("#zipCount");
        this.filterType = $("#filterType");
        this.filterInv = $("#filterInvoice");
        this.results = $("#resultsSection");
        this.dataBody = $("#dataTableBody");
        this.currentBadge = $("#currentFileBadge");
        this.backToZipBtn = $("#backToZipBtn");
        this.canvas = $("#documentCanvas");
        this.ctx = this.canvas.getContext("2d");
        this.previewImg = new Image();
    }

    initState() {
        this.pendingFile = null;
        this.apiFiles = [];
        this.currentIndex = -1;
        this.currentFileData = null;
        this.highlightKeys = [];
        this.imageLoaded = false;
        this.originalFileURL = null;
        this.zoom = 1;
        this.loaderStartTime = 0;
        // PDF rendering state
        this.pdfDoc = null;
        this.pdfPage = null;
        this.currentPdfBytes = null;
        // Image dimensions for polygon scaling
        this.imageWidth = 1000;
        this.imageHeight = 1414;
        
        // FIX 1: Add a buffer for the rendered document to prevent flickering
        this.docBuffer = null; 
    }

    initHeader() {
        const user = getUser();
        $("#userName").textContent = user?.name || "User";
        $("#logoutBtn")?.addEventListener("click", logout);
    }

    bindEvents() {
        this.uploadArea?.addEventListener("click", () => this.fileInput.click());
        this.uploadArea?.addEventListener("dragover", e => { e.preventDefault(); this.uploadArea.classList.add("drag-over"); });
        this.uploadArea?.addEventListener("dragleave", () => this.uploadArea.classList.remove("drag-over"));
        this.uploadArea?.addEventListener("drop", e => {
            e.preventDefault();
            this.uploadArea.classList.remove("drag-over");
            const file = e.dataTransfer?.files?.[0];
            if (file) this.prepareForSubmit(file);
        });
        this.fileInput?.addEventListener("change", e => {
            const file = e.target.files?.[0];
            if (file) this.prepareForSubmit(file);
        });

        $(".browse-link")?.addEventListener("click", (e) => {
            e.stopPropagation(); // This prevents the click from reaching uploadArea
            this.fileInput.click();
        });        
        this.submitBtn?.addEventListener("click", () => this.onSubmitPending());
        this.cancelBtn?.addEventListener("click", () => this.resetAll());
        this.zipBody?.addEventListener("click", e => {
            const btn = e.target.closest("button.btn-view");
            if (btn) this.openResultAt(Number(btn.dataset.idx));
        });
        $("#newAnalysisBtn")?.addEventListener("click", () => this.resetAll());
        $("#downloadAllBtn")?.addEventListener("click", () => this.downloadJSON("all"));
        $("#downloadSelectedBtn")?.addEventListener("click", () => this.downloadJSON("selected"));
        this.backToZipBtn?.addEventListener("click", () => showState("zipContents"));
        $("#zoomIn")?.addEventListener("click", () => this.zoomBy(1.2));
        $("#zoomOut")?.addEventListener("click", () => this.zoomBy(0.8));
        this.dataBody?.addEventListener("click", e => {
            const tr = e.target.closest("tr"); if (!tr) return;
            const cb = tr.querySelector('input[type="checkbox"]'); if (!cb) return;
            if (e.target !== cb) cb.checked = !cb.checked;
            this.toggleHighlight(cb.dataset.key, cb.checked);
        });
        [this.filterType, this.filterInv].forEach(el => el?.addEventListener("input", () => this.applyZipFilters()));

        this.previewImg.onload = () => {
            this.imageLoaded = true;
            this.zoom = 1;
            this.docBuffer = null; // Invalidate buffer on new image load
            this.redraw();
            this.updateZoomLabel();
        };
        this.previewImg.onerror = () => {
            this.imageLoaded = false;
            console.error("Preview image failed to load.");
            this.redraw();
        };
        window.addEventListener("resize", () => this.redraw());
    }

    resetAll() {
        if (this.originalFileURL) URL.revokeObjectURL(this.originalFileURL);
        if (this.pdfDoc) {
            this.pdfDoc.destroy();
            this.pdfDoc = null;
            this.pdfPage = null;
        }
        this.initState();
        this.uploadArea.style.display = 'block';
        this.preSubmitPreview.style.display = 'none';
        this.fileInput.value = '';
        showState('upload');
    }

    prepareForSubmit(file) {
        this.pendingFile = file;
        const isZip = file.name.toLowerCase().endsWith(".zip");
        const iconClass = isZip ? "fa-file-zipper" : (file.type.includes('pdf') ? "fa-file-pdf" : "fa-file-image");
        
        // Create a local URL for single image uploads for faster preview
        if (!isZip && file.type.startsWith('image/')) {
            if (this.originalFileURL) URL.revokeObjectURL(this.originalFileURL);
            this.originalFileURL = URL.createObjectURL(file);
        } else {
            if (this.originalFileURL) URL.revokeObjectURL(this.originalFileURL);
            this.originalFileURL = null;
        }

        this.previewCard.innerHTML = `
            <div class="preview-file-item">
                <i class="fa-solid ${iconClass} icon"></i>
                <div class="preview-file-info">
                    <h4>${file.name}</h4>
                    <p>${(file.size / 1024).toFixed(1)} KB</p>
                </div>
            </div>`;

        this.uploadArea.style.display = 'none';
        this.preSubmitPreview.style.display = 'block';
    }

    startLoader() {
        this.loaderStartTime = Date.now();
        Object.values(this.steps).forEach(el => el.classList.remove('active', 'done'));
        this.stepBar.style.transition = 'width 0.6s ease-out';
        this.stepBar.style.width = '2%';

        const totalMs = 15000;
        const stepMs = totalMs / 3;

        setTimeout(() => { this.steps.upload.classList.add('active'); this.stepBar.style.width = '30%'; }, 100);

        setTimeout(() => {
            this.steps.upload.classList.replace('active', 'done');
            this.steps.extract.classList.add('active');
            this.stepBar.style.width = '60%';
        }, stepMs);

        setTimeout(() => {
            this.steps.extract.classList.replace('active', 'done');
            this.steps.map.classList.add('active');
            this.stepBar.style.width = '85%';
        }, stepMs * 2);
    }
    
    finishLoader() {
        Object.values(this.steps).forEach(el => el.classList.add('done'));
        this.stepBar.style.width = '100%';
    }

    async onSubmitPending() {
        if (!this.pendingFile) return;
        showState('processing');
        this.startLoader();

        const form = new FormData();
        form.append("model", $("#modelSelect")?.value || 'gpt-4.1');
        form.append("file", this.pendingFile);

        const minLoadingTime = 15000;

        try {
            const apiPromise = fetch(`${API_BASE_URL}/upload/`, { method: "POST", body: form })
                .then(async resp => {
                    if (!resp.ok) {
                        const errorText = await resp.text().catch(() => resp.statusText);
                        throw new Error(`Upload failed: ${errorText}`);
                    }
                    return resp.json();
                });

            const apiResult = await apiPromise;

            const elapsedTime = Date.now() - this.loaderStartTime;
            const remainingTime = minLoadingTime - elapsedTime;

            if (remainingTime > 0) {
                await new Promise(resolve => setTimeout(resolve, remainingTime));
            }

            this.finishLoader();
            
            this.apiFiles = apiResult.files || [];
            if (!this.apiFiles.length) throw new Error("No processable documents found.");

            this.currentZipRowsMaster = this.apiFiles.map((it, i) => ({
                name: it.name, 
                type: it.type, 
                invoice: this.extractInvoiceNumber(it.mapped_data) || "—", 
                _idx: i
            }));

            setTimeout(() => {
                if (this.apiFiles.length > 1) {
                    this.applyZipFilters();
                    showState("zipContents");
                } else {
                    this.openResultAt(0);
                }
            }, 400);

        } catch (err) {
            showError(err.message || "An error occurred.");
            this.resetAll();
        }
    }

    extractInvoiceNumber(mapped) {
        if (!mapped) return null;
        const potential = Object.entries(mapped)
            .find(([k]) => /invoice.*(no|number|#|id)/i.test(k.replace(/_/g, ' ')));
        return potential ? potential[1]?.text || potential[1]?.value : null;
    }
    
    applyZipFilters() {
        const type = this.filterType.value;
        const query = this.filterInv.value.toLowerCase();
        const filtered = this.currentZipRowsMaster.filter(r => {
            const typeMatch = type === 'all' || (type === 'pdf' ? r.type.includes('pdf') : !r.type.includes('pdf'));
            const queryMatch = !query || String(r.invoice).toLowerCase().includes(query);
            return typeMatch && queryMatch;
        });
        this.renderZipRows(filtered);
    }
    
    renderZipRows(rows) {
        this.zipCount.textContent = rows.length;
        const typePill = (type) => type.includes('pdf')
            ? `<span class="file-type-badge pdf"><i class="fa-solid fa-file-pdf"></i> PDF</span>`
            : `<span class="file-type-badge image"><i class="fa-solid fa-file-image"></i> Image</span>`;

        this.zipBody.innerHTML = rows.map(f => `
            <tr>
                <td>${f.name}</td><td>${typePill(f.type)}</td><td>${f.invoice}</td>
                <td><button class="btn btn-view" data-idx="${f._idx}">View</button></td>
            </tr>`).join("");
    }

    async openResultAt(apiIndex) {
        const item = this.apiFiles[apiIndex];
        if (!item) return;

        this.currentIndex = apiIndex;
        this.currentFileData = item;
        this.currentBadge.textContent = item.name;
        this.docBuffer = null; // FIX 1: Invalidate buffer for the new document
        
        if (item.preview) {
            this.imageWidth = item.preview.width || 1000;
            this.imageHeight = item.preview.height || 1414;
        }
        
        await this.loadDocumentPreview(item);

        this.buildTableFromMappedData(item.mapped_data || {});
        this.updateSignatureBadge(coerceSignatureVerdict(item.signature));
        
        this.backToZipBtn.style.display = (this.apiFiles.length > 1) ? "inline-flex" : "none";
        showState("results");
        
        // FIX 2: Redraw AFTER the section is visible to ensure canvas has dimensions
        this.redraw();
    }

    async loadDocumentPreview(item) {
        try {
            if (item.preview && item.preview.pdf_bytes) {
                await this.loadPdfPreview(item.preview.pdf_bytes);
            }
            else if (this.apiFiles.length === 1 && this.originalFileURL) {
                this.previewImg.src = this.originalFileURL;
            }
            else {
                this.imageLoaded = false;
            }
        } catch (error) {
            console.error("Failed to load document preview:", error);
            this.imageLoaded = false;
        }
    }

    async loadPdfPreview(pdfBytesBase64) {
        try {
            const binaryString = atob(pdfBytesBase64);
            const bytes = new Uint8Array(binaryString.length);
            for (let i = 0; i < binaryString.length; i++) {
                bytes[i] = binaryString.charCodeAt(i);
            }
            const loadingTask = pdfjsLib.getDocument({ data: bytes });
            this.pdfDoc = await loadingTask.promise;
            this.pdfPage = await this.pdfDoc.getPage(1);

            this.imageLoaded = true;
            this.zoom = 1;
            this.updateZoomLabel();

        } catch (error) {
            console.error("Error loading PDF:", error);
            this.imageLoaded = false;
        }
    }

    buildTableFromMappedData(mappedData) {
        this.highlightKeys = [];
        const entries = Object.entries(mappedData).filter(([key, value]) => 
            value && typeof value === 'object' && (value.text !== undefined || value.polygon !== undefined)
        );

        this.dataBody.innerHTML = entries.map(([key, value]) => `
            <tr data-key="${key}">
                <td><input type="checkbox" data-key="${key}"></td>
                <td>${key.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}</td>
                <td>${(value.text || value.value || "").toString().replace(/\n/g, "<br/>")}</td>
            </tr>`).join("");
    }
    
    toggleHighlight(key, show) {
        const tr = this.dataBody.querySelector(`tr[data-key="${key}"]`);
        if (show) {
            if (!this.highlightKeys.includes(key)) this.highlightKeys.push(key);
            tr?.classList.add("row-active");
        } else {
            this.highlightKeys = this.highlightKeys.filter(k => k !== key);
            tr?.classList.remove("row-active");
        }
        // MODIFIED: This redraw is now much faster as it doesn't re-render the PDF
        this.redraw();
    }
    
    async redraw() {
        if (!this.currentFileData) return;
        
        const container = $("#documentContainer");
        const w = container.clientWidth;
        const h = container.clientHeight;
        if (w === 0 || h === 0) return; // Don't draw if container is not visible

        const dpr = window.devicePixelRatio || 1;
        
        this.canvas.width = w * dpr;
        this.canvas.height = h * dpr;
        this.canvas.style.width = `${w}px`;
        this.canvas.style.height = `${h}px`;
        this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

        this.ctx.clearRect(0, 0, w, h);

        // FIX 1: Check for the off-screen buffer. If it doesn't exist, create it.
        if (!this.docBuffer) {
            await this.renderDocumentToBuffer(w, h);
        }

        // Now, draw from the buffer (fast) instead of re-rendering
        if (this.docBuffer) {
            this.ctx.drawImage(this.docBuffer, 0, 0, w, h);
        }
        
        this.drawPolygonHighlights();
    }

    // FIX 1: New function to render the document to our buffer canvas
    async renderDocumentToBuffer(w, h) {
        // Create a temporary off-screen canvas
        const buffer = document.createElement('canvas');
        buffer.width = w;
        buffer.height = h;
        const bufferCtx = buffer.getContext('2d');

        if (this.imageLoaded) {
            if (this.pdfPage) {
                await this.renderPdfPage(bufferCtx, w, h);
            } else if (this.previewImg.src) {
                this.renderImage(bufferCtx, w, h);
            }
        } else {
            this.renderPlaceholder(bufferCtx, w, h);
        }
        
        // Store the rendered buffer
        this.docBuffer = buffer;
    }

    // MODIFIED: This function now draws to a given context (our buffer)
    async renderPdfPage(ctx, containerWidth, containerHeight) {
        try {
            const viewport = this.pdfPage.getViewport({ scale: 1.0 });
            const sx = containerWidth / viewport.width;
            const sy = containerHeight / viewport.height;
            this.fitScale = Math.min(sx, sy);
            
            const scaledViewport = this.pdfPage.getViewport({ scale: this.fitScale * this.zoom });
            const pageDrawW = scaledViewport.width;
            const pageDrawH = scaledViewport.height;
            
            this.offX = (containerWidth - pageDrawW) / 2;
            this.offY = (containerHeight - pageDrawH) / 2;

            const tempCanvas = document.createElement('canvas');
            const tempCtx = tempCanvas.getContext('2d');
            tempCanvas.width = scaledViewport.width;
            tempCanvas.height = scaledViewport.height;

            const renderContext = { canvasContext: tempCtx, viewport: scaledViewport };
            await this.pdfPage.render(renderContext).promise;
            
            ctx.drawImage(tempCanvas, this.offX, this.offY);

        } catch (error) {
            console.error("Error rendering PDF:", error);
            this.renderPlaceholder(ctx, containerWidth, containerHeight);
        }
    }

    // MODIFIED: This function now draws to a given context (our buffer)
    renderImage(ctx, containerWidth, containerHeight) {
        const sx = containerWidth / this.imageWidth;
        const sy = containerHeight / this.imageHeight;
        this.fitScale = Math.min(sx, sy);
        const pageDrawW = this.imageWidth * this.fitScale * this.zoom;
        const pageDrawH = this.imageHeight * this.fitScale * this.zoom;
        this.offX = (containerWidth - pageDrawW) / 2;
        this.offY = (containerHeight - pageDrawH) / 2;
        
        ctx.drawImage(this.previewImg, this.offX, this.offY, pageDrawW, pageDrawH);
    }
    
    // MODIFIED: This function now draws to a given context (our buffer)
    renderPlaceholder(ctx, containerWidth, containerHeight) {
        const pageDrawW = Math.min(containerWidth * 0.8, 600);
        const pageDrawH = Math.min(containerHeight * 0.8, 800);
        this.offX = (containerWidth - pageDrawW) / 2;
        this.offY = (containerHeight - pageDrawH) / 2;
        this.fitScale = pageDrawW / this.imageWidth;
        
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(this.offX, this.offY, pageDrawW, pageDrawH);
        ctx.strokeStyle = "#e5e7eb";
        ctx.strokeRect(this.offX, this.offY, pageDrawW, pageDrawH);
        ctx.fillStyle = "#6b7280";
        ctx.font = "16px Inter";
        ctx.textAlign = "center";
        ctx.fillText("Preview not available", containerWidth / 2, containerHeight / 2);
    }

    drawPolygonHighlights() {
        if (!this.currentFileData || !this.highlightKeys.length) return;
        
        for (const key of this.highlightKeys) {
            const fieldData = this.currentFileData.mapped_data[key];
            if (!fieldData || !fieldData.polygon) continue;
            
            const absolutePolygon = normalizePolygon(fieldData.polygon, this.imageWidth, this.imageHeight);
            if (absolutePolygon.length < 3) continue;
            
            const canvasPoints = absolutePolygon.map(([x, y]) => this.pageToCanvas([x, y]));
            
            this.ctx.beginPath();
            canvasPoints.forEach(([px, py], i) => {
                if (i === 0) this.ctx.moveTo(px, py);
                else this.ctx.lineTo(px, py);
            });
            this.ctx.closePath();
            
            this.ctx.fillStyle = "rgba(0, 255, 0, 0.2)";
            this.ctx.fill();
            this.ctx.lineWidth = 1.5;
            this.ctx.strokeStyle = "#00ff00";
            this.ctx.stroke();
            
            canvasPoints.forEach(([px, py]) => {
                this.ctx.beginPath();
                this.ctx.arc(px, py, 3, 0, 2 * Math.PI);
                this.ctx.fillStyle = "#00ff00";
                this.ctx.fill();
            });
        }
    }

    pageToCanvas([x, y]) {
        const s = this.fitScale * this.zoom;
        return [x * s + this.offX, y * s + this.offY];
    }
    
    updateZoomLabel() { 
        $("#zoomLevel").textContent = `${Math.round(this.zoom * 100)}%`; 
    }
    
    zoomBy(factor) { 
        this.zoom = Math.max(0.2, Math.min(5, this.zoom * factor)); 
        this.docBuffer = null; // FIX 1: Invalidate buffer on zoom change
        this.redraw(); 
        this.updateZoomLabel(); 
    }
    
    updateSignatureBadge(isSigned) {
        const badge = $("#signatureBadge");
        if (!badge) return;
        badge.className = '';
        if (isSigned === true) { 
            badge.classList.add("signed"); 
            badge.textContent = "Digitally Signed"; 
        } else if (isSigned === false) { 
            badge.classList.add("unsigned"); 
            badge.textContent = "Not Signed"; 
        } else { 
            badge.classList.add("unknown"); 
            badge.textContent = "Signature N/A"; 
        }
    }
    
    downloadJSON(which) {
        if (!this.currentFileData) return;
        
        const keysToInclude = which === "selected" 
            ? this.highlightKeys 
            : Object.keys(this.currentFileData.mapped_data || {});
        
        const out = {};
        keysToInclude.forEach(key => {
            const fieldData = this.currentFileData.mapped_data[key];
            if (fieldData) {
                out[key] = { 
                    text: fieldData.text || fieldData.value || "", 
                    polygon: fieldData.polygon || [] 
                };
            }
        });

        const blob = new Blob([JSON.stringify(out, null, 2)], { type: "application/json" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `${this.pendingFile?.name.split('.')[0] || 'extraction'}.json`;
        a.click();
        URL.revokeObjectURL(a.href);
    }
}

document.addEventListener("DOMContentLoaded", () => new App());