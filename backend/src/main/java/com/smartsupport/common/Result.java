package com.smartsupport.common;

/**
 * 统一返回结果封装——所有接口都返回这个格式。
 * 前端拿到的数据结构永远一样：{ code, message, data }
 * 这样前端处理起来最简单，不用判断这次返回的是对象还是数组还是报错。
 */
public class Result<T> {

    private int code;       // 状态码：200 成功，500 失败
    private String message; // 提示信息
    private T data;         // 真正的数据内容

    public Result() {
    }

    public Result(int code, String message, T data) {
        this.code = code;
        this.message = message;
        this.data = data;
    }

    // ========== 快捷创建方法 ==========

    /** 成功，带数据 */
    public static <T> Result<T> ok(T data) {
        return new Result<>(200, "操作成功", data);
    }

    /** 成功，不带数据 */
    public static <T> Result<T> ok() {
        return new Result<>(200, "操作成功", null);
    }

    /** 失败，返回错误信息 */
    public static <T> Result<T> fail(String message) {
        return new Result<>(500, message, null);
    }

    // ========== Getter / Setter ==========

    public int getCode() { return code; }
    public void setCode(int code) { this.code = code; }

    public String getMessage() { return message; }
    public void setMessage(String message) { this.message = message; }

    public T getData() { return data; }
    public void setData(T data) { this.data = data; }
}
