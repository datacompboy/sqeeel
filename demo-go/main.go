package main

import (
	"database/sql"
	"fmt"
	"html/template"
	"log"
	"net/http"
	"os"

    _ "github.com/lib/pq"
)

type Category struct {
	ID   int
	Name string
}

type Element struct {
	ID      int
	CatID   int
	CatName string
	Name    string
}

type PageData struct {
	Categories       []Category
	Elements         []Element
	SearchName       string
	SelectedCatIDs   []int
	SelectedCatIDsMap map[int]bool
}

var db *sql.DB
var tmpl *template.Template

func main() {
	// DB Connection
	dbConnStr := os.Getenv("DATABASE_URL")
	if dbConnStr == "" {
		dbConnStr = "user=postgres password=postgres dbname=postgres host=localhost port=5432 sslmode=disable"
	}

	var err error
	db, err = sql.Open("postgres", dbConnStr)
	if err != nil {
		log.Fatal(err)
	}
	defer db.Close()

	// Initializing DB
	if err := initDB(); err != nil {
		log.Fatal("DB Init Error: ", err)
	}

	// Templates
	tmpl = template.Must(template.New("index").Parse(indexTmpl))

	// Routes
	http.HandleFunc("/", handleIndex)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	fmt.Printf("Server starting on port %s...\n", port)
	log.Fatal(http.ListenAndServe(":"+port, nil))
}

func initDB() error {
	// Create tables
	queries := []string{
		`CREATE TABLE IF NOT EXISTS categories (id SERIAL PRIMARY KEY, name TEXT NOT NULL)`,
		`CREATE TABLE IF NOT EXISTS elements (id SERIAL PRIMARY KEY, cat_id INT REFERENCES categories(id), name TEXT NOT NULL)`,
	}

	for _, q := range queries {
		if _, err := db.Exec(q); err != nil {
			return err
		}
	}

	// Check if categories exist
	var count int
	err := db.QueryRow("SELECT COUNT(*) FROM categories").Scan(&count)
	if err != nil {
		return err
	}

	if count == 0 {
		fmt.Println("Seeding database...")
		// Insert categories
		categories := []string{"Electronics", "Groceries", "Furniture", "Books", "Clothing"}
		catIDs := make([]int, len(categories))
		for i, name := range categories {
			err := db.QueryRow("INSERT INTO categories (name) VALUES ($1) RETURNING id", name).Scan(&catIDs[i])
			if err != nil {
				return err
			}
		}

		// Insert elements
		elements := map[int][]string{
			0: {"Phone", "Laptop", "Monitor", "Keyboard", "Mouse", "Camera", "Tablet"},
			1: {"Apple", "Milk", "Bread", "Cheese", "Banana", "Tomato", "Chicken"},
			2: {"Chair", "Table", "Desk", "Bed", "Sofa", "Wardrobe", "Shelf"},
			3: {"The Hobbit", "1984", "Dune", "Foundation", "Gatsby", "Odyssey", "Dracula"},
			4: {"T-shirt", "Jeans", "Jacket", "Dress", "Skirt", "Shorts", "Sweater"},
		}

		for idx, names := range elements {
			catID := catIDs[idx]
			for _, name := range names {
				_, err := db.Exec("INSERT INTO elements (cat_id, name) VALUES ($1, $2)", catID, name)
				if err != nil {
					return err
				}
			}
		}
	}

	return nil
}

func handleIndex(w http.ResponseWriter, r *http.Request) {
	if r.Method != "GET" && r.Method != "POST" {
		http.Error(w, "Method Not Allowed", http.StatusMethodNotAllowed)
		return
	}

	var searchName string
	var selectedCatIDs []int

	if r.Method == "POST" {
		searchName = r.FormValue("name")
		for _, catStr := range r.Form["cat"] {
			var id int
			fmt.Sscanf(catStr, "%d", &id)
			if id > 0 {
				selectedCatIDs = append(selectedCatIDs, id)
			}
		}
	}

	// Fetch all categories for the filter
	rows, err := db.Query("SELECT id, name FROM categories ORDER BY name")
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	defer rows.Close()

	var categories []Category
	for rows.Next() {
		var c Category
		if err := rows.Scan(&c.ID, &c.Name); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		categories = append(categories, c)
	}

	// Perform search
	query := `
		SELECT e.id, e.cat_id, c.name, e.name 
		FROM elements e 
		JOIN categories c ON e.cat_id = c.id 
		WHERE 1=1`
	
	var args []interface{}
	argCount := 1

	if searchName != "" {
		query += fmt.Sprintf(" AND e.name ILIKE $%d", argCount)
		args = append(args, searchName+"%")
		argCount++
	}

	catMap := make(map[int]bool)
	if len(selectedCatIDs) > 0 {
		query += fmt.Sprintf(" AND (0=1")
        for _, id := range selectedCatIDs {
            query += fmt.Sprintf(" OR e.cat_id=%d", id)
            catMap[id] = true
        }
        query += ")"
	}

	query += " ORDER BY c.name, e.name"

	eRows, err := db.Query(query, args...)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	defer eRows.Close()

	var elements []Element
	for eRows.Next() {
		var e Element
		if err := eRows.Scan(&e.ID, &e.CatID, &e.CatName, &e.Name); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		elements = append(elements, e)
	}

	data := PageData{
		Categories:       categories,
		Elements:         elements,
		SearchName:       searchName,
		SelectedCatIDs:   selectedCatIDs,
		SelectedCatIDsMap: catMap,
	}

	if err := tmpl.Execute(w, data); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
	}
}

const indexTmpl = `
<!DOCTYPE html>
<html>
<head>
    <title>Demo App</title>
    <style>
        body { font-family: sans-serif; margin: 2em; }
        .filter-section { border: 1px solid #ccc; padding: 1em; background: #f9f9f9; margin-bottom: 2em; }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        th { background-color: #f2f2f2; }
        .cat-list { display: flex; flex-wrap: wrap; gap: 10px; list-style: none; padding: 0; }
        .cat-item { margin-bottom: 5px; }
    </style>
</head>
<body>
    <h1>Element Search</h1>
    
    <div class="filter-section">
        <form method="POST" action="/">
            <div>
                <label>Name Prefix:</label>
                <input type="text" name="name" value="{{.SearchName}}" placeholder="Prefix search...">
            </div>
            <p>Categories:</p>
            <ul class="cat-list">
                {{range .Categories}}
                <li class="cat-item">
                    <input type="checkbox" name="cat" value="{{.ID}}" id="cat-{{.ID}}"
                        {{if index $.SelectedCatIDsMap .ID}}checked{{end}}>
                    <label for="cat-{{.ID}}">{{.Name}}</label>
                </li>
                {{end}}
            </ul>
            <button type="submit">Search</button>
            <a href="/">Clear</a>
        </form>
    </div>

    <table>
        <thead>
            <tr>
                <th>ID</th>
                <th>Category</th>
                <th>Element Name</th>
            </tr>
        </thead>
        <tbody>
            {{range .Elements}}
            <tr>
                <td>{{.ID}}</td>
                <td>{{.CatName}}</td>
                <td>{{.Name}}</td>
            </tr>
            {{else}}
            <tr>
                <td colspan="3">No elements found.</td>
            </tr>
            {{end}}
        </tbody>
    </table>
</body>
</html>
`
