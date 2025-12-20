// Показать модальное окно пополнения
function showDepositModal() {
    document.getElementById('depositModal').style.display = 'block';
}

// Показать модальное окно перевода
function showTransferModal() {
    document.getElementById('transferModal').style.display = 'block';
}

// Закрыть модальное окно
function closeModal(modalId) {
    document.getElementById(modalId).style.display = 'none';
}

// Закрыть модальное окно при клике вне его
window.onclick = function(event) {
    const modals = document.getElementsByClassName('modal');
    for (let modal of modals) {
        if (event.target == modal) {
            modal.style.display = 'none';
        }
    }
}

// Обработка формы пополнения
const depositForm = document.getElementById('depositForm');
if (depositForm) {
    depositForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        
        const amount = parseFloat(document.getElementById('depositAmount').value);
        
        if (amount <= 0) {
            alert('Введите корректную сумму');
            return;
        }
        
        try {
            const response = await fetch('/deposit', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ amount: amount })
            });
            
            const data = await response.json();
            
            if (data.success) {
                alert('✅ ' + data.message);
                closeModal('depositModal');
                document.getElementById('depositAmount').value = '';
            } else {
                alert('Ошибка: ' + data.error);
            }
        } catch (error) {
            alert('Ошибка соединения с сервером');
            console.error(error);
        }
    });
}

// Обработка формы перевода
const transferForm = document.getElementById('transferForm');
if (transferForm) {
    transferForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        
        const recipientAddress = document.getElementById('recipientAddress').value.trim();
        const amount = parseFloat(document.getElementById('transferAmount').value);
        const description = document.getElementById('transferDescription').value;
        
        if (!recipientAddress) {
            alert('Введите адрес получателя');
            return;
        }
        
        if (amount <= 0) {
            alert('Введите корректную сумму');
            return;
        }
        
        try {
            const response = await fetch('/transfer', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ 
                    recipient_address: recipientAddress,
                    amount: amount,
                    description: description
                })
            });
            
            const data = await response.json();
            
            if (data.success) {
                alert(data.message);
                closeModal('transferModal');
                document.getElementById('recipientAddress').value = '';
                document.getElementById('transferAmount').value = '';
                document.getElementById('transferDescription').value = '';
                location.reload();
            } else {
                alert('Ошибка: ' + data.error);
            }
        } catch (error) {
            alert('Ошибка соединения с сервером');
            console.error(error);
        }
    });
}
