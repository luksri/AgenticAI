using Newtonsoft.Json;

namespace Sample.Web.Areas.Admin.Controllers
{
    public class ProductController
    {
        public void UpdateProduct(string data)
        {
            var model = JsonConvert.DeserializeObject<ProductModel>(data);
        }
    }
}
