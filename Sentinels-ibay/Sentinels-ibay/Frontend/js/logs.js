/* =========================================
   CLOCK
========================================= */

function updateClock(){

    const now = new Date();

    const clock =
    document.getElementById("clock");

    const date =
    document.getElementById("date");

    clock.innerText =
    now.toLocaleTimeString();

    date.innerText =
    now.toDateString();
}

setInterval(updateClock,1000);

updateClock();

/* =========================================
   LOG FILTER BUTTONS
========================================= */

const filterButtons =
document.querySelectorAll(
    ".filter-btn"
);

filterButtons.forEach(btn => {

    btn.addEventListener(
        "click",
        () => {

            filterButtons.forEach(
                b => b.classList.remove(
                    "active"
                )
            );

            btn.classList.add(
                "active"
            );

            const type =
            btn.innerText.toLowerCase();

            filterLogs(type);
        }
    );
});

/* =========================================
   FILTER FUNCTION
========================================= */

function filterLogs(type){

    const rows =
    document.querySelectorAll(
        ".log-row"
    );

    rows.forEach(row => {

        row.style.display =
        "grid";

        if(type === "all"){

            return;
        }

        const rowText =
        row.innerText.toLowerCase();

        if(
            !rowText.includes(type)
        ){

            row.style.display =
            "none";
        }
    });
}

/* =========================================
   SEARCH FILTER
========================================= */

const searchInput =
document.querySelector(
    ".search-input"
);

searchInput.addEventListener(
    "keyup",
    () => {

        const value =
        searchInput.value.toLowerCase();

        const rows =
        document.querySelectorAll(
            ".log-row"
        );

        rows.forEach(row => {

            const text =
            row.innerText.toLowerCase();

            if(
                text.includes(value)
            ){

                row.style.display =
                "grid";
            }

            else{

                row.style.display =
                "none";
            }
        });
    }
);

/* =========================================
   LOGOUT
========================================= */

const logoutBtn =
document.querySelector(
    ".logout-btn"
);

logoutBtn.addEventListener(
    "click",
    () => {

        window.location.href =
        "/login";
    }
);