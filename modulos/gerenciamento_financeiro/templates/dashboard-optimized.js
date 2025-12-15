// Dashboard Otimizado - JavaScript Minimalista
// Cache de elementos DOM
const DOM = {
    addTransactionForm: null,
    saveButton: null,
    spinner: null,
    addTransactionModal: null,
    addTransactionTitle: null,
    transactionType: null,
    init() {
        this.addTransactionForm = document.getElementById('addTransactionForm');
        this.saveButton = document.getElementById('saveButton');
        this.spinner = this.saveButton?.querySelector('.spinner-border');
        this.addTransactionModal = document.getElementById('addTransactionModal');
        this.addTransactionTitle = document.getElementById('addTransactionTitle');
        this.transactionType = document.getElementById('transactionType');
    }
};

function upsertTransactionRow(transaction) {
    const existing = document.querySelector(`[data-transaction-id="${transaction.id}"]`);
    if (!existing) {
        addTransactionToTable(transaction);
        return;
    }

    const date = new Date(transaction.transaction_date);
    const dateStr = date.toLocaleDateString('pt-BR');
    const typeIcon = transaction.type === 'income' ? 'bi-arrow-up-circle text-success' : 'bi-arrow-down-circle text-danger';
    const amountClass = transaction.type === 'income' ? 'text-success' : 'text-danger';
    const amountSign = transaction.type === 'income' ? '+' : '-';

    existing.innerHTML = `
        <td class="d-none d-md-table-cell">${dateStr}</td>
        <td>
            <div class="d-flex align-items-center gap-2">
                <i class="bi ${typeIcon}"></i>
                <div>
                    <div class="fw-500">${transaction.description || 'Transação'}</div>
                    <small class="text-muted">${transaction.category?.name || 'Sem categoria'}</small>
                </div>
            </div>
        </td>
        <td class="text-end">
            <span class="${amountClass} fw-bold">${amountSign}R$ ${parseFloat(transaction.amount).toFixed(2).replace('.', ',')}</span>
        </td>
        <td class="text-end">
            <button class="btn btn-sm btn-outline-primary" onclick="editTransaction(${transaction.id})">
                <i class="bi bi-pencil"></i>
            </button>
            <button class="btn btn-sm btn-outline-danger" onclick="deleteTransaction(${transaction.id})">
                <i class="bi bi-trash"></i>
            </button>
        </td>
    `;
}

let currentEditingId = null;

// Inicializar ao carregar
document.addEventListener('DOMContentLoaded', () => {
    DOM.init();
    setupFormListener();
});

// Setup do formulário
function setupFormListener() {
    if (!DOM.addTransactionForm) return;
    
    DOM.addTransactionForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        await saveTransaction();
    });
}

// Salvar transação
async function saveTransaction() {
    if (!DOM.saveButton || !DOM.addTransactionForm) return;
    
    DOM.saveButton.disabled = true;
    if (DOM.spinner) DOM.spinner.classList.remove('d-none');
    
    try {
        const formData = {
            type: document.getElementById('transactionType')?.value,
            description: document.getElementById('description')?.value || '',
            amount: parseFloat(document.getElementById('amount')?.value || 0),
            transaction_date: document.getElementById('transactionDate')?.value,
            category_id: document.getElementById('category')?.value,
            frequency: 'once',
            is_recurring: false,
            is_fixed: document.getElementById('isFixed')?.checked || false
        };
        
        let url = '/gerenciamento-financeiro/api/transactions';
        let method = 'POST';
        const editingId = currentEditingId;
        
        if (editingId) {
            url += `/${editingId}`;
            method = 'PUT';
        }
        
        const response = await fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData)
        });
        
        const result = await response.json();
        
        if (response.ok) {
            bootstrap.Modal.getInstance(DOM.addTransactionModal)?.hide();
            showToast(
                editingId 
                    ? 'Transação atualizada! 🎉'
                    : 'Transação salva! 🎉', 
                'success'
            );
            
            DOM.addTransactionForm.reset();
            currentEditingId = null;
            DOM.addTransactionTitle.innerHTML = '<i class="bi bi-plus-circle me-2"></i>Adicionar Transação';

            if (editingId) {
                upsertTransactionRow(result);
            } else {
                addTransactionToTable(result);
            }
        } else {
            showToast(result.error || 'Erro ao salvar', 'error');
        }
    } catch (error) {
        console.error('Erro:', error);
        showToast('Erro ao salvar transação', 'error');
    } finally {
        DOM.saveButton.disabled = false;
        if (DOM.spinner) DOM.spinner.classList.add('d-none');
    }
}

// Deletar transação
async function deleteTransaction(id) {
    const ok = (window._openConfirmModal)
        ? await window._openConfirmModal({
            title: 'Excluir transação',
            body: 'Tem certeza que deseja excluir esta transação?',
            confirmText: 'Excluir',
            confirmClass: 'btn-danger',
        })
        : window.confirm('Excluir esta transação?');
    if (!ok) return;
    
    try {
        const response = await fetch(`/gerenciamento-financeiro/api/transactions/${id}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            showToast('Transação excluída!', 'success');
            const row = document.querySelector(`[data-transaction-id="${id}"]`);
            if (row) {
                row.style.opacity = '0';
                setTimeout(() => row.remove(), 300);
            }
        } else {
            showToast('Erro ao excluir', 'error');
        }
    } catch (error) {
        console.error('Erro:', error);
        showToast('Erro ao excluir', 'error');
    }
}

// Adicionar transação à tabela
function addTransactionToTable(transaction) {
    const table = document.querySelector('table tbody');
    if (!table) return;
    
    const date = new Date(transaction.transaction_date);
    const dateStr = date.toLocaleDateString('pt-BR');
    const typeIcon = transaction.type === 'income' ? 'bi-arrow-up-circle text-success' : 'bi-arrow-down-circle text-danger';
    const amountClass = transaction.type === 'income' ? 'text-success' : 'text-danger';
    const amountSign = transaction.type === 'income' ? '+' : '-';
    
    const row = document.createElement('tr');
    row.setAttribute('data-transaction-id', transaction.id);
    row.innerHTML = `
        <td class="d-none d-md-table-cell">${dateStr}</td>
        <td>
            <div class="d-flex align-items-center gap-2">
                <i class="bi ${typeIcon}"></i>
                <div>
                    <div class="fw-500">${transaction.description || 'Transação'}</div>
                    <small class="text-muted">${transaction.category?.name || 'Sem categoria'}</small>
                </div>
            </div>
        </td>
        <td class="text-end">
            <span class="${amountClass} fw-bold">${amountSign}R$ ${parseFloat(transaction.amount).toFixed(2).replace('.', ',')}</span>
        </td>
        <td class="text-end">
            <button class="btn btn-sm btn-outline-primary" onclick="editTransaction(${transaction.id})">
                <i class="bi bi-pencil"></i>
            </button>
            <button class="btn btn-sm btn-outline-danger" onclick="deleteTransaction(${transaction.id})">
                <i class="bi bi-trash"></i>
            </button>
        </td>
    `;
    
    table.insertBefore(row, table.firstChild);
    
    const rows = table.querySelectorAll('tr');
    if (rows.length > 10) {
        rows[rows.length - 1].remove();
    }
}

// Toast simples
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `alert alert-${type === 'error' ? 'danger' : type} position-fixed bottom-0 end-0 m-3`;
    toast.style.zIndex = '9999';
    toast.textContent = message;
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// Funções básicas (stubs)
function showAddTransaction(type) {
    currentEditingId = null;
    if (DOM.transactionType) DOM.transactionType.value = type;
    if (DOM.addTransactionTitle) DOM.addTransactionTitle.innerHTML = '<i class="bi bi-plus-circle me-2"></i>Adicionar Transação';
    if (DOM.addTransactionModal) {
        new bootstrap.Modal(DOM.addTransactionModal).show();
    }
}

function editTransaction(id) {
    currentEditingId = id;
    showAddTransaction('income');
}

function showMonthlyHistory() {
    showToast('Funcionalidade em desenvolvimento', 'info');
}

function closeMonthConfirm() {
    showToast('Funcionalidade em desenvolvimento', 'info');
}
