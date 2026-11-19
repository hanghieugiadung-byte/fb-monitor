// ─── Toast Notifications ───────────────────────────────────────────────────

/**
 * showToast(message, type)
 * type: 'success' | 'error' | 'info'
 */
function showToast(message, type = 'success') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const colors = {
    success: 'bg-green-600 border-green-400',
    error:   'bg-red-600 border-red-400',
    info:    'bg-blue-600 border-blue-400',
  };

  const icons = {
    success: '✅',
    error:   '❌',
    info:    'ℹ️',
  };

  const toast = document.createElement('div');
  toast.className = `flex items-center gap-3 px-4 py-3 rounded-lg border text-white text-sm shadow-lg
    transition-all duration-300 opacity-0 translate-x-4 ${colors[type] || colors.info}`;
  toast.innerHTML = `<span>${icons[type] || icons.info}</span><span>${message}</span>`;

  container.appendChild(toast);

  // Animate in
  requestAnimationFrame(() => {
    toast.classList.remove('opacity-0', 'translate-x-4');
  });

  // Auto remove after 4 seconds
  setTimeout(() => {
    toast.classList.add('opacity-0', 'translate-x-4');
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// ─── Confirm Delete ─────────────────────────────────────────────────────────

/**
 * confirmDelete(url, name)
 * Shows a confirm dialog then sends DELETE request to `url`.
 * Reloads the page on success.
 */
async function confirmDelete(url, name) {
  if (!confirm(`Bạn có chắc muốn xóa "${name}" không?\nHành động này không thể hoàn tác.`)) {
    return;
  }

  try {
    const res = await fetch(url, { method: 'DELETE' });
    if (res.ok) {
      showToast(`Đã xóa "${name}" thành công.`, 'success');
      setTimeout(() => location.reload(), 800);
    } else {
      const data = await res.json().catch(() => ({}));
      showToast(data.detail || 'Xóa thất bại.', 'error');
    }
  } catch (err) {
    showToast('Lỗi kết nối máy chủ.', 'error');
  }
}

// ─── Generic fetch helper ───────────────────────────────────────────────────

async function apiPost(url, body = {}) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return res;
}
