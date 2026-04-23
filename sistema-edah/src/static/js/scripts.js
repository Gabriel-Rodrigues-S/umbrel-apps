// Custom JavaScript for SYS_EDAH

// Função para formatar moeda
function formatarMoeda(valor) {
    return 'R$ ' + parseFloat(valor).toFixed(2).replace('.', ',').replace(/(\d)(?=(\d{3})+(?!\d))/g, '$1.');
}

// Função para validar CPF
function validarCPF(cpf) {
    cpf = cpf.replace(/[^\d]+/g, '');
    if (cpf.length !== 11 || /^(\d)\1{10}$/.test(cpf)) return false;
    
    let soma = 0;
    let resto;
    
    for (let i = 1; i <= 9; i++) {
        soma += parseInt(cpf.substring(i - 1, i)) * (11 - i);
    }
    
    resto = (soma * 10) % 11;
    if (resto === 10 || resto === 11) resto = 0;
    if (resto !== parseInt(cpf.substring(9, 10))) return false;
    
    soma = 0;
    for (let i = 1; i <= 10; i++) {
        soma += parseInt(cpf.substring(i - 1, i)) * (12 - i);
    }
    
    resto = (soma * 10) % 11;
    if (resto === 10 || resto === 11) resto = 0;
    if (resto !== parseInt(cpf.substring(10, 11))) return false;
    
    return true;
}

// Função para buscar endereço por CEP
function buscarCEP(cep, callback) {
    cep = cep.replace(/\D/g, '');
    
    if (cep.length === 8) {
        fetch(`https://viacep.com.br/ws/${cep}/json/`)
            .then(response => response.json())
            .then(data => {
                if (!data.erro) {
                    callback(data);
                } else {
                    alert('CEP não encontrado!');
                }
            })
            .catch(error => {
                console.error('Erro ao buscar CEP:', error);
            });
    }
}

// Função para calcular idade
function calcularIdade(dataNascimento) {
    const hoje = new Date();
    const nascimento = new Date(dataNascimento);
    let idade = hoje.getFullYear() - nascimento.getFullYear();
    const mes = hoje.getMonth() - nascimento.getMonth();
    
    if (mes < 0 || (mes === 0 && hoje.getDate() < nascimento.getDate())) {
        idade--;
    }
    
    return idade;
}

// Função para confirmar exclusão
function confirmarExclusao(mensagem = 'Tem certeza que deseja excluir este registro?') {
    return confirm(mensagem);
}

// Função para exibir mensagem de sucesso
function exibirSucesso(mensagem) {
    const alertDiv = document.createElement('div');
    alertDiv.className = 'alert alert-success alert-dismissible fade show position-fixed top-0 end-0 m-3';
    alertDiv.style.zIndex = '9999';
    alertDiv.innerHTML = `
        <i class="fas fa-check-circle"></i> ${mensagem}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    document.body.appendChild(alertDiv);
    
    setTimeout(() => {
        alertDiv.remove();
    }, 5000);
}

// Função para exibir mensagem de erro
function exibirErro(mensagem) {
    const alertDiv = document.createElement('div');
    alertDiv.className = 'alert alert-danger alert-dismissible fade show position-fixed top-0 end-0 m-3';
    alertDiv.style.zIndex = '9999';
    alertDiv.innerHTML = `
        <i class="fas fa-exclamation-triangle"></i> ${mensagem}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    document.body.appendChild(alertDiv);
    
    setTimeout(() => {
        alertDiv.remove();
    }, 5000);
}

// Função para preview de imagem
function previewImagem(input, imgElement) {
    if (input.files && input.files[0]) {
        const reader = new FileReader();
        
        reader.onload = function(e) {
            imgElement.src = e.target.result;
        };
        
        reader.readAsDataURL(input.files[0]);
    }
}

// Auto-hide alerts
document.addEventListener('DOMContentLoaded', function() {
    const alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
    alerts.forEach(alert => {
        setTimeout(() => {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }, 5000);
    });
});

// Prevenir duplo submit de formulários
document.addEventListener('DOMContentLoaded', function() {
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Aguarde...';
            }
        });
    });
});

// Tooltip Bootstrap
document.addEventListener('DOMContentLoaded', function() {
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function(tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
});

// Popover Bootstrap
document.addEventListener('DOMContentLoaded', function() {
    const popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
    popoverTriggerList.map(function(popoverTriggerEl) {
        return new bootstrap.Popover(popoverTriggerEl);
    });
});

/* ============== TEMA CLARO E ESCURO - PERSISTENCIA ============== */

const ThemeManager = {
    transitionTimer: null,

    /**
     * Lê a preferência inicial de tema
     * Prioridade: backend (se autenticado) > localStorage > light (padrão)
     */
    getInitialTheme: function() {
        const htmlTheme = document.documentElement.getAttribute('data-theme');
        if (htmlTheme === 'light' || htmlTheme === 'dark') {
            return htmlTheme;
        }

        // Verificar se há preferência no backend (meta tag na página)
        const metaTheme = document.querySelector('meta[name="theme-preference"]');
        if (metaTheme) {
            return metaTheme.getAttribute('content') || 'light';
        }
        
        // Verificar localStorage (para usuário anonimo)
        try {
            const saved = localStorage.getItem('theme-preference');
            if (saved === 'light' || saved === 'dark') {
                return saved;
            }
        } catch (e) {
            console.warn('localStorage não disponível:', e);
        }
        
        // Fallback padrão
        return 'light';
    },

    /**
     * Aplica o tema ao elemento raiz e atualiza o ícone
     */
    applyTheme: function(theme, options = {}) {
        if (theme !== 'light' && theme !== 'dark') {
            console.error('Tema inválido:', theme);
            return;
        }

        const { animate = false } = options;
        
        const html = document.documentElement;
        const icon = document.getElementById('theme-icon');
        const toggleButton = document.getElementById('theme-toggle');
        
        // Aplicar classe data-theme
        html.setAttribute('data-theme', theme);
        html.style.colorScheme = theme === 'dark' ? 'dark' : 'light';

        if (animate) {
            this.enableTransitionWindow();
        }
        
        // Atualizar ícone
        if (icon) {
            if (theme === 'dark') {
                icon.classList.remove('fa-sun');
                icon.classList.add('fa-moon');
            } else {
                icon.classList.remove('fa-moon');
                icon.classList.add('fa-sun');
            }
        }

        if (toggleButton) {
            const nextLabel = theme === 'dark' ? 'Alternar para tema claro' : 'Alternar para tema escuro';
            toggleButton.setAttribute('aria-pressed', theme === 'dark' ? 'true' : 'false');
            toggleButton.setAttribute('aria-label', nextLabel);
            toggleButton.setAttribute('title', nextLabel);
        }
        
        // Log para observabilidade
        console.log('[Theme] Aplicado:', theme);
    },

    /**
     * Habilita transicao visual por uma janela curta apenas no toggle manual.
     */
    enableTransitionWindow: function() {
        const html = document.documentElement;
        html.classList.add('theme-transition');

        if (this.transitionTimer) {
            clearTimeout(this.transitionTimer);
        }

        this.transitionTimer = setTimeout(() => {
            html.classList.remove('theme-transition');
            this.transitionTimer = null;
        }, 320);
    },

    /**
     * Persiste preferência localmente ou envia para backend (se autenticado)
     */
    persistTheme: function(theme) {
        // Salvar localmente (persistencia para anonimo)
        try {
            localStorage.setItem('theme-preference', theme);
        } catch (e) {
            console.warn('Falha ao salvar em localStorage:', e);
            // Continuar mesmo sem localStorage - tema permanece da sessão
        }
        
        // Se usuario está autenticado, sincronizar com backend
        const isAuthenticated = document.querySelector('[data-user-id]') !== null 
                                || document.body.classList.contains('authenticated');
        if (isAuthenticated) {
            this.syncWithBackend(theme);
        }
    },

    /**
     * Sincroniza preferência com backend via API
     */
    syncWithBackend: function(theme) {
        // Encontrar token CSRF (Django)
        const csrf = document.querySelector('[name="csrfmiddlewaretoken"]')?.value 
                     || document.cookie.split('; ').find(row => row.startsWith('csrftoken='))?.split('=')[1];
        
        fetch('/api/user/theme/', {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrf || ''
            },
            body: JSON.stringify({ theme: theme })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`Backend sync failed: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            console.log('[Theme] Sincronizado com backend:', data);
        })
        .catch(error => {
            // Log erro mas nao bloqueia uso - tema ja foi aplicado localmente
            console.warn('[Theme] Erro ao sincronizar com backend:', error);
        });
    },

    /**
     * Vincula evento do botão de toggle
     */
    bindThemeToggle: function() {
        const button = document.getElementById('theme-toggle');
        if (!button) return;
        
        const toggle = () => {
            const current = document.documentElement.getAttribute('data-theme') || 'light';
            const next = current === 'light' ? 'dark' : 'light';
            
            this.applyTheme(next, { animate: true });
            this.persistTheme(next);
        };
        
        // Click com mouse
        button.addEventListener('click', toggle);
        
        // Ativacao por teclado (Enter/Space)
        button.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                toggle();
            }
        });
        
        console.log('[Theme] Toggle vinculado');
    },

    /**
     * Inicializa sistema de tema (chamado ao carregar documento)
     */
    init: function() {
        // 1. Obter preferência inicial
        const theme = this.getInitialTheme();
        
        // 2. Aplicar imediatamente (antes do paint perceptivel)
        this.applyTheme(theme, { animate: false });
        
        // 3. Vincular toggle quando DOM estiver pronto
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.bindThemeToggle());
        } else {
            this.bindThemeToggle();
        }
        
        console.log('[Theme] Inicializado. Tema atual:', theme);
    }
};

// Inicializar tema assim que o script carrega
ThemeManager.init();

