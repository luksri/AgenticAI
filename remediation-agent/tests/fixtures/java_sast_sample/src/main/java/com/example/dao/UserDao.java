package com.example.dao;

import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;

public class UserDao {
    private final Connection connection;

    public UserDao(Connection connection) {
        this.connection = connection;
    }

    public User findByUsername(String username) throws SQLException {
        Statement stmt = connection.createStatement();
        String query = "SELECT * FROM users WHERE username = '" + username + "'";
        ResultSet rs = stmt.executeQuery(query);
        if (rs.next()) {
            return new User(rs.getString("username"), rs.getString("email"));
        }
        return null;
    }
}
