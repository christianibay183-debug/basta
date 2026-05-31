const mainContainer = document.getElementById("mainContainer");
const loginForm     = document.getElementById("loginForm");

setTimeout(() => {
    mainContainer.classList.add("show");

    // If the server returned an error, shake the card after it fades in
    const errorEl = document.querySelector(".error");
    if (errorEl) {
        triggerShake();
    }
}, 1600);

function triggerShake() {
    loginForm.classList.remove("shake");
    // Force reflow so the animation restarts cleanly if called again
    void loginForm.offsetWidth;
    loginForm.classList.add("shake");
    loginForm.addEventListener("animationend", () => {
        loginForm.classList.remove("shake");
    }, { once: true });
}

// Client-side: shake on empty submit attempt before the request hits the server
loginForm.addEventListener("submit", (e) => {
    const username = loginForm.querySelector("input[name='username']").value.trim();
    const password = loginForm.querySelector("input[name='password']").value.trim();
    if (!username || !password) {
        e.preventDefault();
        triggerShake();
    }
});

function updateClock() {
    const now = new Date();
    const future = new Date(now.getTime() + (8 * 60 * 60 * 1000));
    document.getElementById("clock").innerHTML = future.toLocaleTimeString();
}

setInterval(updateClock, 1000);
updateClock();
