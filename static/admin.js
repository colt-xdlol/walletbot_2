let adminData = null;

// Загрузка данных при загрузке страницы
window.addEventListener('DOMContentLoaded', async function() {
    await loadAdminData();
});

// Загрузка данных админ-панели
async function loadAdminData() {
    try {
        const response = await fetch('/admin/get_data');
        const data = await response.json();
        
        if (data.success) {
            adminData = data;
            renderUsers(data.users);
            renderTransactions(data.transactions);
            renderSettings(data.settings);
        } else {
            alert('Ошибка загрузки данных');
        }
    } catch (error) {
        console.error('Ошибка:', error);
        alert('Ошибка соединения с сервером');
    }
}

// Переключение вкладок
function showTab(tabName) {
    // Скрываем все вкладки
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.remove('active');
    });
    
    // Убираем активный класс у всех кнопок
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    
    // Показываем выбранную вкладку
    document.getElementById(tabName + 'Tab').classList.add('active');
    
    // Активируем кнопку
    event.target.classList.add('active');
}

// Отображение пользователей
function renderUsers(users) {
    const container = document.getElementById('usersList');
    
    if (users.length === 0) {
        container.innerHTML = '<p>Нет пользователей</p>';
        return;
    }
    
    let html = '<table><thead><tr><th>TG ID</th><th>Имя</th><th>Баланс</th><th>Статус</th><th>Дата</th><th>Действия</th></tr></thead><tbody>';
    
    users.forEach(user => {
        html += `
            <tr>
                <td>${user.tg_id}</td>
                <td>${user.username || user.first_name || 'Без имени'}</td>
                <td>${user.balance.toFixed(2)} ₽</td>
                <td><span class="badge ${user.banned ? 'banned' : 'active'}">${user.banned ? 'Забанен' : 'Активен'}</span></td>
                <td>${user.created_at}</td>
                <td>
                    ${user.banned 
                        ? `<button class="btn-small btn-unban" onclick="unbanUser(${user.tg_id})">Разбанить</button>`
                        : `<button class="btn-small btn-ban" onclick="banUser(${user.tg_id})">Забанить</button>`
                    }
                </td>
            </tr>
        `;
    });
    
    html += '</tbody></table>';
    container.innerHTML = html;
}

// Отображение транзакций
function renderTransactions(transactions) {
    const container = document.getElementById('transactionsList');
    
    if (transactions.length === 0) {
        container.innerHTML = '<p>Нет транзакций</p>';
        return;
    }
    
    let html = '<table><thead><tr><th>TG ID</th><th>Пользователь</th><th>Тип</th><th>Сумма</th><th>Описание</th><th>Дата</th></tr></thead><tbody>';
    
    transactions.forEach(trans => {
        html += `
            <tr>
                <td>${trans.tg_id}</td>
                <td>${trans.username || 'Без имени'}</td>
                <td>${trans.type.toUpperCase()}</td>
                <td class="${trans.type === 'deposit' || trans.type === 'admin_give' ? 'positive' : 'negative'}">
                    ${trans.type === 'deposit' || trans.type === 'admin_give' ? '+' : '-'}${trans.amount.toFixed(2)} ₽
                </td>
                <td>${trans.description || '-'}</td>
                <td>${trans.date}</td>
            </tr>
        `;
    });
    
    html += '</tbody></table>';
    container.innerHTML = html;
}

// Отображение настроек
function renderSettings(settings) {
    document.getElementById('minDeposit').value = settings.min_deposit;
    document.getElementById('maxDeposit').value = settings.max_deposit;
    document.getElementById('minWithdraw').value = settings.min_withdraw;
    document.getElementById('maxWithdraw').value = settings.max_withdraw;
}

// Выдача баланса
async function giveBalance() {
    const tgId = document.getElementById('giveUserId').value;
    const amount = parseFloat(document.getElementById('giveAmount').value);
    
    if (!tgId || !amount || amount <= 0) {
        alert('Заполните все поля корректно');
        return;
    }
    
    try {
        const response = await fetch('/admin/give_balance', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                tg_id: parseInt(tgId),
                amount: amount
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            alert('Баланс выдан успешно');
            document.getElementById('giveUserId').value = '';
            document.getElementById('giveAmount').value = '';
            await loadAdminData();
        } else {
            alert('Ошибка: ' + data.error);
        }
    } catch (error) {
        console.error('Ошибка:', error);
        alert('Ошибка соединения с сервером');
    }
}

// Бан пользователя
async function banUser(tgId) {
    if (!confirm('Забанить этого пользователя?')) return;
    
    try {
        const response = await fetch('/admin/ban_user', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ tg_id: tgId })
        });
        
        const data = await response.json();
        
        if (data.success) {
            alert('Пользователь забанен');
            await loadAdminData();
        } else {
            alert('Ошибка: ' + data.error);
        }
    } catch (error) {
        console.error('Ошибка:', error);
        alert('Ошибка соединения с сервером');
    }
}

// Разбан пользователя
async function unbanUser(tgId) {
    if (!confirm('Разбанить этого пользователя?')) return;
    
    try {
        const response = await fetch('/admin/unban_user', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ tg_id: tgId })
        });
        
        const data = await response.json();
        
        if (data.success) {
            alert('Пользователь разбанен');
            await loadAdminData();
        } else {
            alert('Ошибка: ' + data.error);
        }
    } catch (error) {
        console.error('Ошибка:', error);
        alert('Ошибка соединения с сервером');
    }
}

// Сохранение настроек
document.getElementById('settingsForm').addEventListener('submit', async function(e) {
    e.preventDefault();
    
    const settings = {
        min_deposit: parseFloat(document.getElementById('minDeposit').value),
        max_deposit: parseFloat(document.getElementById('maxDeposit').value),
        min_withdraw: parseFloat(document.getElementById('minWithdraw').value),
        max_withdraw: parseFloat(document.getElementById('maxWithdraw').value)
    };
    
    try {
        const response = await fetch('/admin/update_settings', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(settings)
        });
        
        const data = await response.json();
        
        if (data.success) {
            alert('Настройки сохранены');
        } else {
            alert('Ошибка: ' + data.error);
        }
    } catch (error) {
        console.error('Ошибка:', error);
        alert('Ошибка соединения с сервером');
    }
});

